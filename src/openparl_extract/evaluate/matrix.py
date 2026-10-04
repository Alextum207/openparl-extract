"""Feasibility matrix: schema field x (level | language | parliament) -> consistent / partial / not_representable.

Availability = share of affairs in the column group whose field holds a usable value. F1 comes from the gold set
only when the cell has >= min_gold_n reviewed entries.

IMPORTANT: the classification thresholds are configuration, not truth; change `Thresholds` and the verdicts move.
`consistent*` / `partial*` (asterisk, `verified=False`) is AVAILABILITY-ONLY: the field is filled in, but no gold
evidence says the values are right. Only cells without an asterisk are backed by gold F1.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import pandas as pd

from openparl_extract.evaluate.gold import GoldDoc
from openparl_extract.evaluate.metrics import FLAG_FAMILIES, body_id, _collect, _compute, flag_rates
from openparl_extract.models import Affair

Classification = Literal["consistent", "partial", "not_representable", "insufficient_data"]


@dataclass
class Thresholds:
    consistent_availability: float = 0.8
    consistent_f1: float = 0.8
    absent_availability: float = 0.2
    min_gold_n: int = 5


def _has(v) -> bool:
    return v is not None and v.value is not None


def _dec(k):
    return lambda a: a.decision is not None and _has(getattr(a.decision, k))


def _role(r):
    return lambda a: any(x.role.value is not None and x.role.value.value == r for x in a.actors)


FIELDS: dict[str, Callable[[Affair], bool]] = {
    "title": lambda a: _has(a.title),
    "reference_number": lambda a: _has(a.reference_number),
    "affair_type": lambda a: _has(a.affair_type),
    "actors.submitter": _role("submitter"),
    "actors.co_signatory": _role("co_signatory"),
    "addressed_body": lambda a: _has(a.addressed_body),
    "affair_text": lambda a: _has(a.affair_text),
    "justification": lambda a: _has(a.justification),
    "questions": lambda a: any(_has(q.text) for q in a.questions),
    "answers": lambda a: any(_has(x.text) for x in a.answers),
    "executive_reasoning": lambda a: _has(a.executive_reasoning),
    "decision.outcome": _dec("outcome"),
    "decision.date": _dec("date"),
    "procedural_history": lambda a: bool(a.procedural_history),
    "annexes": lambda a: bool(a.annexes),
}
LEVELS, LANGS = ("federal", "cantonal", "municipal"), ("de", "fr", "it", "rm")


def classify(availability: float, f1: float | None, n_affairs: int, th: Thresholds) -> Classification:
    if n_affairs < 3:
        return "insufficient_data"
    if availability < th.absent_availability:
        return "not_representable"
    if availability >= th.consistent_availability and (f1 is None or f1 >= th.consistent_f1):
        return "consistent"
    return "partial"


def _columns(affairs: list[Affair]) -> list[tuple[str, str, list[Affair]]]:
    cols = [("level", lv, [a for a in affairs if a.source.level.value == lv]) for lv in LEVELS]
    cols += [("language", lg, [a for a in affairs if a.source.language.value == lg]) for lg in LANGS]
    cols += [("parliament", p, [a for a in affairs if body_id(a) == p])
             for p in sorted({body_id(a) for a in affairs})]
    return cols


def build_matrix(affairs: list[Affair], gold: list[GoldDoc], th: Thresholds = Thresholds()) -> pd.DataFrame:
    rows_all = _collect(affairs, gold)
    recs = []
    for gt, g, members in _columns(affairs):
        ids = {a.source.openparldata_id for a in members}
        ms = _compute([r for r in rows_all if r[0].affair_id in ids], 90)
        for field, has in FIELDS.items():
            avail = sum(has(a) for a in members) / len(members) if members else 0.0
            m = ms.get(field)  # gold keys equal matrix field names for gold-backed rows
            n_gold = m.n_reviewed if m else 0
            f1 = m.f1 if m and n_gold >= th.min_gold_n else None
            recs.append({"field": field, "group_type": gt, "group": g, "n_affairs": len(members),
                         "availability": avail, "f1": f1, "n_gold": n_gold,
                         "classification": classify(avail, f1, len(members), th), "verified": f1 is not None})
    return pd.DataFrame(recs)


def matrix_wide(df: pd.DataFrame) -> pd.DataFrame:
    star = ~df.verified & df.classification.isin(["consistent", "partial"])
    d = df.assign(cell=df.classification + star.map({True: "*", False: ""}))
    return d.pivot(index="field", columns="group", values="cell").reindex(list(FIELDS))


def _md_table(df: pd.DataFrame) -> str:
    cols = [df.index.name or "field", *map(str, df.columns)]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join([str(i), *map(str, r)]) + " |" for i, r in zip(df.index, df.values)]
    return "\n".join(lines)


def write_matrix(out_dir: Path, affairs: list[Affair], gold: list[GoldDoc], th: Thresholds = Thresholds()) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    long = build_matrix(affairs, gold, th)
    wide = matrix_wide(long)
    long.to_csv(out / "feasibility_matrix_long.csv", index=False)
    wide.to_csv(out / "feasibility_matrix.csv")
    fr = flag_rates(affairs)
    fr = fr[fr.group_type == "parliament"].set_index("group").drop(columns="group_type")
    fr = fr[["n_affairs", *FLAG_FAMILIES]].round(2)
    md = f"""# Feasibility matrix

{_md_table(wide.fillna("-"))}

Legend: `consistent` = filled in for >= {th.consistent_availability:.0%} of affairs (and F1 >= {th.consistent_f1} where gold exists);
`partial` = in between; `not_representable` = filled in for < {th.absent_availability:.0%} of affairs;
`insufficient_data` = fewer than 3 affairs. A trailing `*` means availability-only, NOT verified against the gold set.

Thresholds (configuration, not truth): consistent_availability={th.consistent_availability},
consistent_f1={th.consistent_f1}, absent_availability={th.absent_availability}, min_gold_n={th.min_gold_n}.

## Review-flag rates per parliament

High `segmentation_failed` rates mark structural differences (documents that do not follow the common
question / answer / decision layout).

{_md_table(fr)}
"""
    (out / "feasibility_matrix.md").write_text(md, encoding="utf-8")
