"""Deterministic verification (no LLM): quotes must exist in the cited block, vocab and dates must be valid.

Failing values become not_found + a review flag; offsets are always computed here, never taken from the model.
"""
import re
from datetime import date

from pydantic import BaseModel
from rapidfuzz import fuzz

from openparl_extract.extract.schemas import ExtractedItem, ExtractionResult
from openparl_extract.models import Answer, Decision, DecisionOutcome, Provenance, Question, Value
from openparl_extract.parse.blocks import Block

_TOKEN = re.compile(r"­|-[ \t]*\r?\n\s*|\s+|.", re.S)  # soft hyphen | hyphen+newline join | whitespace run | char
_APOS = {"’": "'", "‘": "'", "ʼ": "'"}
_DATE_IN_TEXT = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\.\d{1,2}\.\d{4}")


class VerifiedParts(BaseModel):
    affair_text: Value[str]
    justification: Value[str]
    executive_reasoning: Value[str]
    questions: list[Question]
    answers: list[Answer]
    decision: Decision | None
    review_flags: list[str]
    prompt_versions: dict[str, str]


def normalise(text: str) -> tuple[str, list[int]]:
    """Normalised text for matching plus idx[i] = offset in the ORIGINAL text of normalised char i.

    Collapses whitespace, drops soft hyphens and hyphen+line-break joins, casefolds, unifies apostrophes.
    """
    out: list[str] = []
    idx: list[int] = []
    for m in _TOKEN.finditer(text):
        tok = m.group()
        if tok == "­" or (len(tok) > 1 and tok[0] == "-"):
            continue
        if tok.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(m.start())
            continue
        for c in _APOS.get(tok, tok).lower():  # lower() may expand (e.g. dotted I); all map to the same origin
            out.append(c)
            idx.append(m.start())
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def locate(quote: str, block: Block, threshold: int) -> tuple[int, int] | None:
    """(char_start, char_end) of quote inside block.text (original offsets), or None."""
    nq, _ = normalise(quote)
    nb, idx = normalise(block.text)
    if not nq or not nb:
        return None
    pos = nb.find(nq)
    if pos >= 0:
        s, e = pos, pos + len(nq)
    else:
        if len(nq) > len(nb):  # alignment would swap the arguments and match the block inside the quote
            return None
        al = fuzz.partial_ratio_alignment(nq, nb)
        if al is None or al.score < threshold:
            return None
        s, e = al.dest_start, al.dest_end
        while s < e and nb[s] == " ":
            s += 1
        while e > s and nb[e - 1] == " ":
            e -= 1
        if e <= s or fuzz.ratio(nq, nb[s:e]) < threshold:  # the WHOLE quote must be matched
            return None
    # end offset: original index of the last matched char + 1 (extends over a trailing multi-char token)
    last = idx[e - 1]
    m = _TOKEN.match(block.text, last)
    return idx[s], (m.end() if m else last + 1)


def _flagged(flag: str) -> tuple[Value, list[str]]:
    return Value(value=None, status="not_found", review_flag=flag), [flag]


def _verified_quote(item: ExtractedItem | None, by_id: dict[str, Block], threshold: int
                    ) -> tuple[Provenance | None, list[str]]:
    """Provenance for the item's quote, or (None, flags). Item absent/empty -> (None, [])."""
    if item is None or item.value is None or not item.value.strip():
        return None, []
    block = by_id.get(item.block_id) if item.block_id else None
    if block is None:
        return None, [f"block_not_found:{item.block_id}"]
    if not item.quote or not item.quote.strip():
        return None, ["missing_quote"]
    span = locate(item.quote, block, threshold)
    if span is None:
        return None, [f"quote_not_found:{block.id}"]
    return Provenance(page=block.page, block_id=block.id, char_start=span[0], char_end=span[1],
                      quote=block.text[span[0]:span[1]]), []


def _supported(value: str, quote: str, threshold: int) -> bool:
    nv, nq = normalise(value)[0], normalise(quote)[0]
    # value may be a part of the quote, but must not add text beyond it (partial_ratio alone scores 100 then)
    return len(nv) <= len(nq) * 1.1 and fuzz.partial_ratio(nv, nq) >= threshold


def verify_item(item: ExtractedItem | None, blocks_by_id: dict[str, Block], threshold: int = 90
                ) -> tuple[Value[str], list[str]]:
    prov, flags = _verified_quote(item, blocks_by_id, threshold)
    if prov is None:
        return (Value[str](value=None, status="not_found", review_flag=flags[0] if flags else None), flags)
    if not _supported(item.value, prov.quote, threshold):
        return Value[str](value=None, status="not_found", review_flag="value_not_supported"), ["value_not_supported"]
    return Value[str](value=item.value, status="extracted", provenance=[prov]), []


def parse_date(raw: str) -> date | None:
    """ISO YYYY-MM-DD or D.M.YYYY; anything else is None."""
    s = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", s):
            return date(*map(int, s.split("-")))
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", s):
            d, mo, y = map(int, s.split("."))
            return date(y, mo, d)
    except ValueError:
        pass
    return None


def _verify_outcome(item, by_id, threshold):
    prov, flags = _verified_quote(item, by_id, threshold)
    if item is None or item.value is None or not item.value.strip():
        return Value[DecisionOutcome](status="not_found"), []
    if prov is None:
        return Value[DecisionOutcome](status="not_found", review_flag=flags[0]), flags
    code = re.sub(r"[\s\-]+", "_", item.value.strip().lower())
    try:
        outcome = DecisionOutcome(code)
    except ValueError:
        flag = f"vocab_invalid:outcome:{item.value}"
        return Value[DecisionOutcome](status="not_found", review_flag=flag), [flag]
    return Value[DecisionOutcome](value=outcome, status="extracted", provenance=[prov]), []


def _verify_date(item, by_id, threshold):
    prov, flags = _verified_quote(item, by_id, threshold)
    if item is None or item.value is None or not item.value.strip():
        return Value[date](status="not_found"), []
    if prov is None:
        return Value[date](status="not_found", review_flag=flags[0]), flags
    parsed = parse_date(item.value)
    if parsed is None:
        return Value[date](status="not_found", review_flag="date_unparseable"), ["date_unparseable"]
    # supported: quote contains the raw value, or some date inside the quote parses to the same day
    in_quote = item.value.strip() in prov.quote or parsed in {parse_date(m) for m in _DATE_IN_TEXT.findall(prov.quote)}
    if not in_quote:
        return Value[date](status="not_found", review_flag="value_not_supported"), ["value_not_supported"]
    return Value[date](value=parsed, status="extracted", provenance=[prov]), []


def _verify_decision(dec, by_id, threshold):
    if dec is None:
        return None, []
    outcome, f1 = _verify_outcome(dec.outcome, by_id, threshold)
    when, f2 = _verify_date(dec.date, by_id, threshold)
    body, f3 = verify_item(dec.body, by_id, threshold)
    return Decision(outcome=outcome, date=when, body=body), f1 + f2 + f3


def _verify_qa(result: ExtractionResult, by_id, threshold):
    flags: list[str] = []
    questions = []
    for q in result.questions:
        text, f = verify_item(q.text, by_id, threshold)
        questions.append(Question(id=q.id, text=text))
        flags += f
    counts: dict[str, int] = {}
    for q in questions:
        counts[q.id] = counts.get(q.id, 0) + 1
    flags += [f"duplicate_question_id:{i}" for i, n in counts.items() if n > 1]
    answers = []
    per_q: dict[str, int] = {}
    for a in result.answers:
        text, f = verify_item(a.text, by_id, threshold)
        qid, flag = a.question_id, None  # review_flag of a value = all its flags joined with ";"
        if qid is not None and counts.get(qid, 0) > 1:
            qid, flag = None, f"answer_ambiguous_question:{a.question_id}"
        elif qid is not None and qid not in counts:
            qid, flag = None, f"answer_unknown_question:{a.question_id}"
        elif qid is not None:
            per_q[qid] = per_q.get(qid, 0) + 1
            if per_q[qid] >= 2:
                flag = f"multiple_answers:{qid}"
        if flag:
            flags.append(flag)
            text.review_flag = flag if text.review_flag is None else f"{text.review_flag};{flag}"
        answers.append(Answer(question_id=qid, text=text))
        flags += f
    return questions, answers, flags


def check_date_order(submitted: date | None, answered: date | None, decided: date | None) -> list[str]:
    pairs = [("submitted", submitted, "answered", answered), ("answered", answered, "decided", decided),
             ("submitted", submitted, "decided", decided)]
    return [f"date_order:{n1}_after_{n2}" for n1, d1, n2, d2 in pairs if d1 and d2 and d1 > d2]


def verify(result: ExtractionResult, blocks: list[Block], threshold: int = 90) -> VerifiedParts:
    by_id = {b.id: b for b in blocks}
    flags: list[str] = []
    singles = {}
    for name in ("affair_text", "justification", "executive_reasoning"):
        singles[name], f = verify_item(getattr(result, name), by_id, threshold)
        flags += f
    questions, answers, f = _verify_qa(result, by_id, threshold)
    flags += f
    decision, f = _verify_decision(result.decision, by_id, threshold)
    flags += f
    flags += [f"extract_error:{e}" for e in result.errors]
    return VerifiedParts(**singles, questions=questions, answers=answers, decision=decision,
                         review_flags=list(dict.fromkeys(flags)), prompt_versions=result.prompt_versions)
