"""Turn one gold entry into one small question (one field, one click)."""
from typing import Literal

from pydantic import BaseModel

from openparl_extract.evaluate.gold import GoldDoc, GoldEntry
from openparl_extract.models import Affair, DecisionOutcome, Value
from openparl_extract.parse.blocks import ParsedDoc
from openparl_extract.review.i18n import t

# order in which the queue serves the fields of one document
FIELD_ORDER = ("affair_text", "question:*", "answer:*", "executive_reasoning", "justification", "addressed_body",
               "decision.outcome", "decision.date", "decision.body")


def field_rank(field: str) -> int:
    key = field.split(":")[0] + ":*" if ":" in field else field
    return FIELD_ORDER.index(key) if key in FIELD_ORDER else len(FIELD_ORDER)


def prompt_key(field: str) -> str:
    return field.split(":")[0] if ":" in field else field


class Question(BaseModel):
    doc_key: str
    field: str
    kind: Literal["text", "vocab", "date", "presence"]
    value_kind: Literal["text", "vocab", "date"]
    prompt: str
    pipeline_value: str | None
    quote: str | None = None
    block_id: str | None = None
    page: int | None = None
    page_count: int | None = None
    question_text: str | None = None
    vocab: list[str] | None = None
    allow_free_text: bool
    options: list[str]
    needs_gold_on_wrong: bool


def _value_of(affair: Affair | None, field: str) -> tuple[Value | None, str | None]:
    """(schema Value for this field key, paired question text for answers)."""
    if affair is None:
        return None, None
    if field.startswith("question:"):
        qid = field.split(":", 1)[1]
        return next((q.text for q in affair.questions if q.id == qid), None), None
    if field.startswith("answer:"):
        i = int(field.split(":", 1)[1])
        if not 0 <= i < len(affair.answers):
            return None, None
        a = affair.answers[i]
        qt = next((q.text.value for q in affair.questions if q.id == a.question_id), None) if a.question_id else None
        return a.text, qt
    if field.startswith("decision."):
        return getattr(affair.decision, field.split(".", 1)[1], None) if affair.decision else None, None
    return getattr(affair, field, None), None


def build_question(doc: GoldDoc, entry: GoldEntry, affair: Affair | None, parsed: ParsedDoc | None,
                   lang: str, doc_key: str | None = None) -> Question:
    f = entry.field
    value_kind = "vocab" if f == "decision.outcome" else "date" if f == "decision.date" else "text"
    null = entry.pipeline_value is None
    kind = "presence" if null else value_kind
    v, qt = _value_of(affair, f)
    prov = v.provenance[0] if v is not None and v.provenance and not null else None
    pk = prompt_key(f)
    if null:
        options = ["no", "yes", "unsure"]
    else:
        options = ["correct", "wrong", "not_in_document", "unsure"]
    return Question(
        doc_key=doc_key or f"{doc.body_key}_{doc.affair_id}", field=f, kind=kind, value_kind=value_kind,
        prompt=t(lang, ("p." if null else "q.") + pk), pipeline_value=entry.pipeline_value,
        quote=prov.quote if prov else None, block_id=prov.block_id if prov else None,
        page=prov.page if prov else None, page_count=parsed.page_count if parsed else None,
        question_text=qt, vocab=[o.value for o in DecisionOutcome] if value_kind == "vocab" else None,
        allow_free_text=value_kind != "vocab", options=options, needs_gold_on_wrong=null)
