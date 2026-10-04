"""Gold-set metrics, provenance validity and flag rates.

Per field family (question:* -> questions, answer:* -> answers), over reviewed gold entries only:
  TP = pipeline non-null & verdict correct          FP = non-null & (wrong | not_in_document)
  FN = pipeline null & verdict wrong (a miss)       TN = null & not_in_document (null was right)
  precision = TP/(TP+FP)  recall = TP/(TP+FN)  f1 = harmonic mean  (None when undefined)
  not_found_correctness = TN/(TN+FN)
  hallucination_rate = #(non-null & not_in_document) / #(non-null reviewed)
Entries whose pipeline_value differs from the current output are `stale` (output changed after review) and skipped.
"""
import json
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel
from rapidfuzz import fuzz

from openparl_extract.evaluate.gold import GoldDoc, GoldEntry, pipeline_values
from openparl_extract.extract.schemas import ExtractedItem, ExtractionResult
from openparl_extract.models import Affair, Value
from openparl_extract.verify.verify import VerifiedParts

REVIEWED = ("correct", "wrong", "not_in_document")
FLAG_FAMILIES = ("segmentation_failed", "no_document", "parse_failed", "no_text_found", "quote_not_found",
                 "language_ambiguous", "unmapped_event", "ambiguous_role", "disagreement", "no_extraction")
FAILURE_KINDS = ("quote_not_found", "block_not_found", "value_not_supported", "missing_quote", "vocab_invalid",
                 "date_unparseable")


def family(key: str) -> str:
    return key.split(":")[0] + "s" if ":" in key else key


def _ratio(n, d):
    return n / d if d else None


def _norm(s: str) -> str:
    return " ".join(s.split())


def values_match(a: str, b: str, threshold: int = 90) -> bool:
    return fuzz.ratio(_norm(a), _norm(b)) >= threshold


class FieldMetrics(BaseModel):
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    near_miss: int = 0  # informational: marked wrong but within threshold of gold_value
    n_reviewed: int = 0
    n_unsure_or_unreviewed: int = 0
    n_nonnull_reviewed: int = 0
    n_hallucinated: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    not_found_correctness: float | None = None
    hallucination_rate: float | None = None
    stale: list[str] = []


def load_outputs(dir: Path, name: str = "affair.json") -> list[Affair]:
    return [Affair.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(Path(dir).rglob(name))]


def _collect(affairs: list[Affair], gold: list[GoldDoc]) -> list[tuple[GoldDoc, GoldEntry, bool]]:
    """(doc, entry, stale) for every gold entry."""
    cur = {a.source.openparldata_id: pipeline_values(a) for a in affairs}
    out = []
    for d in gold:
        vals = cur.get(d.affair_id, {})
        for e in d.entries:
            out.append((d, e, e.field not in vals or vals[e.field] != e.pipeline_value))
    return out


def _finish(m: FieldMetrics) -> None:
    m.precision, m.recall = _ratio(m.tp, m.tp + m.fp), _ratio(m.tp, m.tp + m.fn)
    if m.precision is not None and m.recall is not None:
        m.f1 = 2 * m.precision * m.recall / (m.precision + m.recall) if m.precision + m.recall > 0 else 0.0
    m.not_found_correctness = _ratio(m.tn, m.tn + m.fn)
    m.hallucination_rate = _ratio(m.n_hallucinated, m.n_nonnull_reviewed)


def _compute(rows, threshold: int) -> dict[str, FieldMetrics]:
    ms: dict[str, FieldMetrics] = {}
    for d, e, stale in rows:
        m = ms.setdefault(family(e.field), FieldMetrics(stale=[]))
        if stale:
            m.stale.append(f"{d.affair_id}|{e.field}")
        elif e.verdict not in REVIEWED:
            m.n_unsure_or_unreviewed += 1
        else:
            m.n_reviewed += 1
            if e.pipeline_value is not None:
                m.n_nonnull_reviewed += 1
                if e.verdict == "correct":
                    m.tp += 1
                else:
                    m.fp += 1
                    m.n_hallucinated += e.verdict == "not_in_document"
                    if e.verdict == "wrong" and e.gold_value and values_match(e.pipeline_value, e.gold_value, threshold):
                        m.near_miss += 1
            elif e.verdict == "wrong":
                m.fn += 1
            else:
                m.tn += 1
    for m in ms.values():
        _finish(m)
    ms["_all"] = _sum(list(ms.values()))
    return ms


def _sum(parts: list[FieldMetrics]) -> FieldMetrics:
    t = FieldMetrics(stale=[])
    for p in parts:
        for k in ("tp", "fp", "fn", "tn", "near_miss", "n_reviewed", "n_unsure_or_unreviewed",
                  "n_nonnull_reviewed", "n_hallucinated"):
            setattr(t, k, getattr(t, k) + getattr(p, k))
        t.stale += p.stale
    _finish(t)
    return t


def field_metrics(affairs: list[Affair], gold: list[GoldDoc], match_threshold: int = 90) -> dict[str, FieldMetrics]:
    return _compute(_collect(affairs, gold), match_threshold)


def body_id(a: Affair) -> str:
    """Stable parliament id: Source.body_key, falling back to the localized name for old outputs."""
    return a.source.body_key or a.source.parliament


def _group_of(doc: GoldDoc, a: Affair | None, by: str):
    if a is None:  # affair missing: fall back to the GoldDoc copy
        return doc.body_key if by == "parliament" else getattr(doc, by)
    if by == "parliament":
        return body_id(a)
    if by == "is_scanned":
        return a.source.is_scanned
    if by == "affair_type":
        return a.affair_type.value
    return getattr(a.source, by)


def group_metrics(affairs: list[Affair], gold: list[GoldDoc],
                  by: Literal["level", "language", "parliament", "is_scanned", "affair_type"],
                  match_threshold: int = 90) -> pd.DataFrame:
    by_id = {a.source.openparldata_id: a for a in affairs}
    groups: dict = {}
    for r in _collect(affairs, gold):
        v = _group_of(r[0], by_id.get(r[0].affair_id), by)
        groups.setdefault(str(getattr(v, "value", v)), []).append(r)
    recs = [{"field": f, "group_type": by, "group": g, **m.model_dump(exclude={"stale"})}
            for g, rows in sorted(groups.items()) for f, m in _compute(rows, match_threshold).items()]
    return pd.DataFrame(recs)


# ---------- provenance ----------
class ProvenanceStats(BaseModel):
    n_values: int = 0
    n_valid: int = 0
    failures: dict[str, int] = {k: 0 for k in FAILURE_KINDS}
    validity: float | None = None


def _pairs(raw: ExtractionResult, ver: VerifiedParts) -> list[tuple[ExtractedItem | None, Value]]:
    p = [(getattr(raw, k), getattr(ver, k)) for k in ("affair_text", "justification", "executive_reasoning")]
    p += [(q.text, v.text) for q, v in zip(raw.questions, ver.questions)]
    p += [(a.text, v.text) for a, v in zip(raw.answers, ver.answers)]
    if raw.decision and ver.decision:
        p += [(getattr(raw.decision, k), getattr(ver.decision, k)) for k in ("outcome", "date", "body")]
    return p


def provenance_validity(raw: ExtractionResult, verified: VerifiedParts) -> ProvenanceStats:
    """Non-null model values vs those that survived verify. Failure kind = prefix of the value's first flag."""
    s = ProvenanceStats(failures={k: 0 for k in FAILURE_KINDS})
    for item, v in _pairs(raw, verified):
        if item is None or item.value is None or not item.value.strip():
            continue
        s.n_values += 1
        if v.status == "extracted":
            s.n_valid += 1
        elif v.review_flag:
            kind = v.review_flag.split(";")[0].split(":")[0]
            s.failures[kind] = s.failures.get(kind, 0) + 1
    s.validity = _ratio(s.n_valid, s.n_values)
    return s


def aggregate_provenance(stats: list[ProvenanceStats]) -> ProvenanceStats:
    t = ProvenanceStats(failures={k: 0 for k in FAILURE_KINDS})
    for s in stats:
        t.n_values += s.n_values
        t.n_valid += s.n_valid
        for k, n in s.failures.items():
            t.failures[k] = t.failures.get(k, 0) + n
    t.validity = _ratio(t.n_valid, t.n_values)
    return t


# ---------- flags ----------
def flag_rates(affairs: list[Affair]) -> pd.DataFrame:
    """Share of affairs carrying each flag family, per parliament / level / language."""
    fams = list(FLAG_FAMILIES)
    fams += sorted({f.split(":")[0] for a in affairs for f in a.review_flags} - set(fams))
    groups: dict[tuple[str, str], list[set[str]]] = {}
    for a in affairs:
        flags = {f.split(":")[0] for f in a.review_flags}
        s = a.source
        for gt, g in (("parliament", body_id(a)), ("level", s.level.value), ("language", s.language.value)):
            groups.setdefault((gt, g), []).append(flags)
    recs = [{"group_type": gt, "group": g, "n_affairs": len(fl),
             **{f: sum(f in x for x in fl) / len(fl) for f in fams}} for (gt, g), fl in sorted(groups.items())]
    return pd.DataFrame(recs, columns=["group_type", "group", "n_affairs", *fams])


def write_report(out_dir: Path, affairs: list[Affair], gold: list[GoldDoc],
                 provenance: ProvenanceStats | None = None, match_threshold: int = 90) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ms = field_metrics(affairs, gold, match_threshold)
    (out / "metrics.json").write_text(json.dumps({k: m.model_dump() for k, m in ms.items()}, indent=2), encoding="utf-8")
    pd.DataFrame([{"field": k, **m.model_dump(exclude={"stale"}), "n_stale": len(m.stale)}
                  for k, m in ms.items()]).to_csv(out / "metrics_by_field.csv", index=False)
    by = ("level", "language", "parliament", "is_scanned", "affair_type")
    pd.concat([group_metrics(affairs, gold, b, match_threshold) for b in by], ignore_index=True
              ).to_csv(out / "metrics_by_group.csv", index=False)
    flag_rates(affairs).to_csv(out / "flag_rates.csv", index=False)
    (out / "provenance.json").write_text((provenance or ProvenanceStats()).model_dump_json(indent=2), encoding="utf-8")
