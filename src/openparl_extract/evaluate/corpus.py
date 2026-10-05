"""Stratified candidate corpus for the gold set (level x language x scanned x type), picked from the live API.

Everything is deterministic given (seed, API state). No document is downloaded here, only listings are read.
"""
import json
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from openparl_extract.ingest.api import OpenParlDataClient
from openparl_extract.merge.language import detect_language
from openparl_extract.merge.mapping import (
    BODY_TYPE_TO_LEVEL,
    HARMONIZED_TYPE_TO_AFFAIR_TYPE,
)
from openparl_extract.merge.merge import LANG_ORDER, pick
from openparl_extract.models import AffairType, Level
from openparl_extract.segment.patterns import PATTERNS
from openparl_extract.segment.rules import MAX_HEADING_LEN, normalise

LANGS = ("de", "fr", "it")
LEVELS = ("federal", "cantonal", "municipal")
LEVEL_SHARE = {"federal": 8, "cantonal": 22, "municipal": 15}  # of 45
SCANNED_MIN_SHARE, TYPE_MAX_SHARE, SCANNED_CHARS = 0.15, 0.4, 200
EMPTY_BODY_PAGE_FACTOR = 5
FEDERAL_PAGE_FACTOR = 30
POOL_FACTOR = 2  # candidates wanted per quota slot before we stop paging


class CorpusEntry(BaseModel):
    affair_id: int
    body_key: str
    body_name: str | None = None
    level: Level
    language: str
    affair_type: str
    original_type_label: str | None = None
    state: str | None = None
    doc_id: int
    doc_name: str | None = None
    n_pdf_docs: int
    has_plain_text: bool
    scanned_guess: bool
    lifecycle_complete: bool
    reason: str


# ---------- choose the PDF per affair ----------
def _pdfs(docs: list[dict]) -> list[dict]:
    return [d for d in docs if d.get("format") == "application/pdf" and d.get("url_oparl")]


def _score(doc: dict) -> int:
    text = doc.get("text") or ""
    hit = set()
    for line in text.splitlines():
        if len(line) <= MAX_HEADING_LEN:
            t = normalise(line)
            hit |= {s for s in ("executive_answer", "questions", "decision") if PATTERNS[s].match(t)}
    return (3 * ("executive_answer" in hit) + 2 * ("questions" in hit) + ("decision" in hit)
            + bool(text.strip()))


def choose_doc(docs: list[dict]) -> dict | None:
    """The PDF most likely to hold the substance; ties -> earliest in API order."""
    pdfs = _pdfs(docs or [])
    return max(pdfs, key=lambda d: (_score(d), -pdfs.index(d))) if pdfs else None


# ---------- lifecycle ----------
# Live evidence (2026-10-04): list rows carry `state_name` (verbatim dict: ZH "Erledigt"/"abgeschlossen", CHE "Erledigt",
# TI "Evaso"/"Non evaso", cities "InBearbeitung", GE {}), `end_date` (set for ZH "Erledigt"); `state_name_harmonized` is {}.
# Events are NOT in list rows. Rule: open wording -> False; else end_date set or done wording -> True; else unknown (None).
_OPEN = re.compile(r"non evas|nicht erledigt|unbeantwort|nicht beantwort|in ?bearbeitung|eingereicht|deposit|depos"
                   r"|pendent|haengig|hangig|offen|en cours|geplant|previst|trasformat|non traite")
_DONE = re.compile(r"erledigt|abgeschlossen|beantwortet|liquid|evas[oa]|traite|termine|classe|repondu|abgeschrieben"
                   r"|abgelehnt|angenommen|ueberwiesen|uberwiesen|risposto|respint|accett|adottat|cloture|zuruckgezogen"
                   r"|zurueckgezogen|ausgefuhrt")


def lifecycle(a: dict) -> bool | None:
    state = " ".join(normalise(v) for k in ("state_name", "state_name_harmonized")
                     for v in (a.get(k) or {}).values() if v)
    if _OPEN.search(state):
        return False
    if a.get("end_date") or _DONE.search(state):
        return True
    return None


# ---------- candidate evaluation ----------
def _language(a: dict, doc: dict, body: dict, flags: list[str]) -> str | None:
    lang = (doc.get("language") or "").lower()
    if lang in LANGS:
        return lang
    cands = [k for k in (a.get("title") or {}) if k in LANGS]
    if len(cands) == 1:
        return cands[0]
    if cands:
        flags.append("language_guess")
        return detect_language(doc.get("text") or "", cands) or next(k for k in LANG_ORDER if k in cands)
    lang = (body.get("lang") or "").lower()
    if lang in LANGS:
        flags.append("language_guess")
        return lang
    return None


@dataclass
class Cand:
    entry: CorpusEntry
    score: int
    order: int = 0


def _level(body: dict) -> Level | None:
    if body.get("type") == "country" and body.get("country_key", body.get("body_key")) != "CHE":
        return None
    return BODY_TYPE_TO_LEVEL.get(body.get("type"))


def evaluate_candidate(a: dict, body: dict, level: Level) -> Cand | None:
    docs = (a.get("docs") or {}).get("data") or []
    doc = choose_doc(docs)
    state = lifecycle(a)
    if doc is None or state is False:
        return None
    flags: list[str] = []
    lang = _language(a, doc, body, flags)
    if lang is None:
        return None
    text = (doc.get("text") or "").strip()
    atype = HARMONIZED_TYPE_TO_AFFAIR_TYPE.get(a.get("type_harmonized_id"), AffairType.other)
    scanned = len(text) < SCANNED_CHARS
    flags += (["lifecycle_unknown"] if state is None else []) + (["scanned_guess"] if scanned else [])
    e = CorpusEntry(
        affair_id=a["id"], body_key=str(a["body_key"]), body_name=pick(body.get("name"), lang), level=level,
        language=lang, affair_type=atype.value,
        original_type_label=pick(a.get("type_name"), lang) or pick(a.get("type_harmonized"), lang),
        state=pick(a.get("state_name"), lang), doc_id=doc["id"], doc_name=doc.get("name"), n_pdf_docs=len(_pdfs(docs)),
        has_plain_text=bool(text), scanned_guess=scanned, lifecycle_complete=state is True,
        reason=f"doc_score={_score(doc)}" + "".join("; " + f for f in flags))
    return Cand(e, _score(doc))


# ---------- quotas ----------
def body_cap(cell: tuple[str, str], quota: int) -> int:
    """Max entries per parliament within one cell (breadth); federal has a single body."""
    return quota if cell[0] == "federal" else max(2, math.ceil(quota / 4))


def quotas(n_total: int) -> dict[tuple[str, str], int]:
    fed, can = round(n_total * LEVEL_SHARE["federal"] / 45), round(n_total * LEVEL_SHARE["cantonal"] / 45)
    out = {}
    for lv, n in (("federal", fed), ("cantonal", can), ("municipal", n_total - fed - can)):
        de = math.ceil(n / 2)
        fr = math.ceil((n - de) / 2)
        out |= {(lv, "de"): de, (lv, "fr"): fr, (lv, "it"): n - de - fr}
    return out


class _Budget(Exception):
    pass


def pick_corpus(client: OpenParlDataClient, n_total: int = 45, seed: int = 7, max_requests: int = 300,
                pages_per_body: int = 3, page_size: int = 50) -> tuple[list[CorpusEntry], dict]:
    rng = random.Random(seed)
    quota, errors, state = quotas(n_total), [], {"calls": 0, "budget_out": False}

    def call(fn, *a, **k):
        if state["calls"] >= max_requests:
            raise _Budget
        state["calls"] += 1
        return fn(*a, **k)

    summary: dict = {"n_total": n_total, "seed": seed, "errors": errors}
    try:
        bodies = call(client.list_bodies)
    except _Budget:
        bodies = []
    except Exception as e:
        errors.append({"body_key": "*bodies*", "error": f"{type(e).__name__}: {e}"})
        bodies = []
    # only bodies the scraper indexes (live: `indexed`; missing flag = assume yes); level via BODY_TYPE_TO_LEVEL
    queue: dict[str, list[tuple[dict, Level]]] = {lv: [] for lv in LEVELS}
    for b in sorted(bodies, key=lambda b: str(b.get("body_key"))):
        lv = _level(b)
        if lv and b.get("indexed", True) is not False:
            queue[lv.value].append((b, lv))
    for q in queue.values():
        rng.shuffle(q)

    def serves(b: dict, lang: str) -> bool:
        bl = (b.get("lang") or "").lower()
        return bl == lang or bl not in LANGS  # language-less bodies (CHE) can serve any language

    pool: dict[tuple[str, str], list[Cand]] = {c: [] for c in quota}
    visited: set[str] = set()

    def next_body(cell):
        return next((x for x in queue[cell[0]] if str(x[0]["body_key"]) not in visited and serves(x[0], cell[1])), None)

    def page_limit(lv: Level, found: int) -> int:
        if not found:
            return pages_per_body * EMPTY_BODY_PAGE_FACTOR
        if lv is Level.federal and any(len(pool[c]) < POOL_FACTOR * q for c, q in quota.items() if c[0] == "federal"):
            return pages_per_body * FEDERAL_PAGE_FACTOR
        return pages_per_body

    n_cand, seen_ids, dups = 0, set(), 0
    try:
        while True:
            def full(c):  # enough candidates AND from enough different parliaments
                return (len(pool[c]) >= POOL_FACTOR * quota[c]
                        and len({x.entry.body_key for x in pool[c]}) >= math.ceil(quota[c] / body_cap(c, quota[c])))

            open_ = [c for c in quota if quota[c] and not full(c) and next_body(c)]
            if not open_:
                break
            cell = max(open_, key=lambda c: (POOL_FACTOR * quota[c] - len(pool[c]), quota[c], c))
            body, lv = next_body(cell)
            key = str(body["body_key"])
            visited.add(key)
            try:
                # Page 0 is offset 0 (gives total_records); later pages jump to random offsets, because documents are
                # sparse and clustered (live: CHE has docs on ~0-30% of rows, only in some offset windows).
                # A body that has yielded no candidate yet gets EMPTY_BODY_PAGE_FACTOR x more pages; the single federal body keeps
                # paging (up to FEDERAL_PAGE_FACTOR x) until its pool is full.
                total, used, found, k = None, set(), 0, 0
                while k < page_limit(lv, found):
                    off = 0 if k == 0 or not total else rng.randrange(0, max(1, total - page_size + 1))
                    if not total and k:
                        off = k * page_size
                    k += 1
                    if off in used:
                        continue
                    used.add(off)
                    page = call(client.list_affairs, body_key=key, limit=page_size, offset=off, expand_docs=True)
                    total = total or page["meta"].get("total_records")
                    for a in page["data"]:
                        if a["id"] in seen_ids:  # overlapping windows / same affair via another body
                            dups += 1
                            continue
                        seen_ids.add(a["id"])
                        c = evaluate_candidate(a, body, lv)
                        if c and (lv.value, c.entry.language) in pool:
                            c.order, n_cand, found = n_cand, n_cand + 1, found + 1
                            pool[(lv.value, c.entry.language)].append(c)
                    if not page["data"] or (not total and not page["meta"].get("has_more")):
                        break
            except _Budget:
                raise
            except Exception as e:  # a failing body never aborts the run
                errors.append({"body_key": key, "error": f"{type(e).__name__}: {e}"})
    except _Budget:
        state["budget_out"] = True

    entries, unmet = _select(pool, quota, n_total, rng), []
    got = {c: sum((e.level.value, e.language) == c for e in entries) for c in quota}
    for c, q in quota.items():
        if got[c] < q:
            n_vis = sum(str(x[0]["body_key"]) in visited for x in queue[c[0]])
            why = ("max_requests exhausted" if state["budget_out"] else
                   f"no more usable candidates ({len(pool[c])} pooled; {n_vis} {c[0]} bodies visited)")
            unmet.append({"level": c[0], "language": c[1], "wanted": q, "got": got[c], "reason": why})

    def count(f):
        return {k: sum(f(e) == k for e in entries) for k in sorted({f(e) for e in entries})}

    summary |= {"n": len(entries), "requests": state["calls"],
                "level": {k: sum(e.level.value == k for e in entries) for k in LEVELS},
                "language": count(lambda e: e.language), "scanned_guess": sum(e.scanned_guess for e in entries),
                "affair_type": count(lambda e: e.affair_type), "body": count(lambda e: e.body_key), "unmet": unmet,
                "duplicates_skipped": dups}
    return entries, summary


def _select(pool, quota, n_total, rng) -> list[CorpusEntry]:
    for c in pool.values():
        rng.shuffle(c)  # shuffle first, every later min() is order-stable
    type_cap = max(1, math.ceil(TYPE_MAX_SHARE * n_total))
    types: dict[str, int] = {}
    chosen: set[int] = set()  # never the same affair twice, even if the pool held duplicates
    picked: dict[tuple[str, str], list[Cand]] = {c: [] for c in quota}

    def take(cell, scanned_only: bool, limit: int, capped: bool = True):
        cap = body_cap(cell, quota[cell]) if capped else quota[cell]
        while len(picked[cell]) < limit:
            ok = [c for c in pool[cell] if c.entry.affair_id not in chosen and (c.entry.scanned_guess or not scanned_only)
                  and sum(p.entry.body_key == c.entry.body_key for p in picked[cell]) < cap]
            ok = [c for c in ok if types.get(c.entry.affair_type, 0) < type_cap] or ok
            if not ok:
                return
            best = min(ok, key=lambda c: (not c.entry.lifecycle_complete, types.get(c.entry.affair_type, 0), -c.score))
            picked[cell].append(best)
            chosen.add(best.entry.affair_id)
            types[best.entry.affair_type] = types.get(best.entry.affair_type, 0) + 1

    for cell in quota:  # phase 1: scanned documents, so the share of scanned PDFs does not depend on luck
        take(cell, True, min(quota[cell], math.ceil(SCANNED_MIN_SHARE * quota[cell])))
    for cell in quota:
        take(cell, False, quota[cell])
    for cell in quota:  # soft cap: relax the per-body limit rather than leave a quota unmet
        take(cell, False, quota[cell], capped=False)
    return [c.entry for cell in quota for c in picked[cell]]


# ---------- io ----------
def write_corpus(path: Path, entries: list[CorpusEntry], summary: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": [e.model_dump(mode="json") for e in entries], "summary": summary},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def load_corpus(path: Path) -> tuple[list[CorpusEntry], dict]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return [CorpusEntry.model_validate(e) for e in d["entries"]], d["summary"]


def format_summary(s: dict) -> str:
    def row(name, d):
        return f"  {name:<14}" + "  ".join(f"{k}={v}" for k, v in d.items())

    lines = [f"corpus: {s.get('n', 0)} of {s.get('n_total')} entries, {s.get('requests', 0)} API requests "
             f"(seed {s.get('seed')})",
             row("level", s.get("level", {})), row("language", s.get("language", {})),
             f"  {'scanned_guess':<14}{s.get('scanned_guess', 0)}", row("affair_type", s.get("affair_type", {})),
             f"  duplicates_skipped: {s.get('duplicates_skipped', 0)}", f"  unmet: {len(s.get('unmet', []))}"]
    lines += [f"    {u['level']}/{u['language']}: {u['got']}/{u['wanted']} ({u['reason']})" for u in s.get("unmet", [])]
    lines.append(f"  errors: {len(s.get('errors', []))}")
    lines += [f"    {e['body_key']}: {e['error']}" for e in s.get("errors", [])]
    return "\n".join(lines)
