"""Gold-set format shared by the evaluation and the review UI (which writes these files).

One JSON file per document: `<body_key>_<affair_id>.json`, a serialised `GoldDoc`.

Field keys: single values `affair_text`, `justification`, `executive_reasoning`, `addressed_body`,
`decision.outcome`, `decision.date`, `decision.body`; list items `question:<id>` and `answer:<index>`
(index into Affair.answers).

Verdict semantics
- pipeline value NOT null:
    correct          the value is right
    wrong            a different true value exists in the document (optionally `gold_value`)
    not_in_document  the value is not supported by the source (= hallucination)
    unsure
- pipeline value null (not_found):
    not_in_document  null was right
    wrong            the information IS in the document (a miss); `gold_value` says what
    unsure
`unreviewed` and `unsure` entries are excluded from all metrics but counted in coverage.
"""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from openparl_extract.models import AffairType, Affair, Language, Level

Verdict = Literal["correct", "wrong", "not_in_document", "unsure", "unreviewed"]
SINGLE_FIELDS = ("affair_text", "justification", "executive_reasoning", "addressed_body",
                 "decision.outcome", "decision.date", "decision.body")


class GoldEntry(BaseModel):
    field: str
    pipeline_value: str | None
    verdict: Verdict = "unreviewed"
    gold_value: str | None = None  # required when verdict == "wrong" and a true value exists in the doc
    gold_block_id: str | None = None
    reviewer: str | None = None
    timestamp: str | None = None  # ISO
    note: str | None = None


class GoldDoc(BaseModel):
    affair_id: str
    body_key: str
    level: Level
    language: Language
    is_scanned: bool | None = None
    affair_type: AffairType | None = None
    entries: list[GoldEntry] = []


def _s(v) -> str | None:
    """String form of a Value (None when absent / not_found)."""
    x = getattr(v, "value", None)
    return None if x is None else str(x.isoformat() if hasattr(x, "isoformat") else x)


def pipeline_values(affair: Affair) -> dict[str, str | None]:
    """Field key -> current pipeline value (None = not_found) for every key of this affair."""
    out = {k: _s(getattr(affair, k)) for k in ("affair_text", "justification", "executive_reasoning",
                                                "addressed_body")}
    d = affair.decision
    for k in ("outcome", "date", "body"):
        out[f"decision.{k}"] = _s(getattr(d, k)) if d else None
    for q in affair.questions:
        out[f"question:{q.id}"] = _s(q.text)
    for i, a in enumerate(affair.answers):
        out[f"answer:{i}"] = _s(a.text)
    return out


def entries_for_affair(affair: Affair) -> list[GoldEntry]:
    """Draft (unreviewed) entries: the prefill for the review UI."""
    return [GoldEntry(field=k, pipeline_value=v) for k, v in pipeline_values(affair).items()]


def load_gold(dir: Path) -> list[GoldDoc]:
    return [GoldDoc.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(Path(dir).glob("*.json"))]


def save_gold(doc: GoldDoc, dir: Path) -> Path:
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    p = dir / f"{doc.body_key}_{doc.affair_id}.json"
    p.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return p
