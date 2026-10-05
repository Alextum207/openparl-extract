"""Merge: API metadata (from_metadata) + verified LLM extraction -> final Affair.

Metadata always wins; the extraction is only a cross-check. Disagreements are logged and flagged, never overwritten.
"""
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from openparl_extract.merge.language import detect_language
from openparl_extract.merge.mapping import (
    AUTHOR_COSIGNER_RE,
    AUTHOR_SUBMITTER_RE,
    BODY_TYPE_TO_LEVEL,
    EVENT_TO_PROCEDURAL_STATE,
    HARMONIZED_TYPE_TO_AFFAIR_TYPE,
    PERSON_ROLE_TO_ACTOR_ROLE,
)
from openparl_extract.models import (
    Actor,
    ActorRole,
    Affair,
    AffairType,
    Language,
    Level,
    ProceduralEvent,
    ProceduralState,
    Provenance,
    Reference,
    Source,
    Value,
)
from openparl_extract.parse.blocks import Block, ParsedDoc
from openparl_extract.segment.rules import SegmentResult
from openparl_extract.verify.verify import VerifiedParts, check_date_order

LANG_ORDER = ("de", "fr", "it", "rm")
_APOSTROPHES = "’‘´`"
_BODY_PHRASES = re.compile(
    r"\b(regierungsrat|bundesrat|stadtrat|gemeinderat|staatsrat|conseil d'etat|conseil federal|conseil communal"
    r"|conseil municipal|consiglio di stato|consiglio federale|consiglio comunale|municipio)(?=(?:e?s)?\b)")  # lookahead: genitive "Regierungsrates" still matches


def pick(d: dict | None, lang: str | None = None) -> str | None:
    """Value of a language dict: document language, then de/fr/it/rm, then whatever is there."""
    d = {k: v for k, v in (d or {}).items() if v}
    return next((d[k] for k in (lang, *LANG_ORDER) if k in d), next(iter(d.values()), None))


def _meta(v) -> Value:
    return Value(value=v, status="from_metadata") if v is not None else Value(status="not_found")


def _date(raw: str | None) -> date | None:
    try:
        return datetime.fromisoformat(raw).date() if raw else None
    except ValueError:
        return None


def _fold(text: str) -> str:
    """Length-preserving accent/case folding so offsets in the folded text equal offsets in the original."""
    return "".join("'" if c in _APOSTROPHES else unicodedata.normalize("NFKD", c)[0].lower() for c in text)


def addressed_body(parsed: ParsedDoc | None, segments: SegmentResult | None) -> Value[str]:
    if parsed is None or segments is None:
        return Value(status="not_found")
    by_id = {b.id: b for b in parsed.blocks}
    for bid, section in segments.headings:
        b = by_id.get(bid)
        m = b and section == "executive_answer" and _BODY_PHRASES.search(_fold(b.text))
        if m:
            quote = b.text[m.start():m.end()]
            return Value(value=quote, status="extracted",
                         provenance=[Provenance(page=b.page, block_id=b.id, char_start=m.start(), char_end=m.end(),
                                                quote=quote)])
    return Value(status="not_found")


def _primary(manifest: dict) -> dict:
    return next((d for d in manifest.get("docs", []) if d.get("doc_id") == manifest.get("primary_doc_id")), {})


def _language(a: dict, manifest: dict, parsed: ParsedDoc | None, flags: list[str]) -> str | None:
    lang = (_primary(manifest).get("language") or "").lower()
    if lang in Language._value2member_map_:
        return lang
    cands = [k for k in (a.get("title") or {}) if k in Language._value2member_map_]
    if len(cands) <= 1:
        return cands[0] if cands else None
    flags.append("language_ambiguous:" + ",".join(cands))
    detected = detect_language(" ".join(b.text for b in parsed.blocks), cands) if parsed else None
    if detected:
        flags.append(f"language_detected:{detected}")
        return detected
    return next(k for k in LANG_ORDER if k in cands)  # fixed preference, never dict order


def _source(a: dict, manifest: dict, parsed: ParsedDoc | None, body: dict | None, flags: list[str]) -> Source:
    key, body = a.get("body_key"), body or {}
    btype = body.get("type")
    if btype == "country" and body.get("country_key", key) != "CHE":
        raise ValueError(f"body {key} is a foreign country, not a Swiss level")
    level = BODY_TYPE_TO_LEVEL.get(btype) or (Level.federal if key == "CHE" else None)
    if level is None:
        raise ValueError(f"cannot determine level for body {key!r} (type {btype!r}); pass the /v1/bodies entry")
    primary = _primary(manifest)
    lang = _language(a, manifest, parsed, flags)
    if lang is None:
        raise ValueError("cannot determine document language")
    return Source(openparldata_id=str(a["id"]), parliament=pick(body.get("name"), lang) or key, body_key=key, level=level,
                  language=lang, document_url=primary.get("url_oparl"), pdf_sha256=primary.get("pdf_sha256"),
                  is_scanned=parsed.is_scanned if parsed else None)


def _actors(a: dict, lang: str, flags: list[str]) -> list[Actor]:
    out = []
    for c in sorted((a.get("contributors") or {}).get("data", []), key=lambda c: c.get("position") or 0):
        harmonized = (c.get("role_harmonized") or {}).get("en")
        verbatim = pick(c.get("role"), lang) or ""
        role = PERSON_ROLE_TO_ACTOR_ROLE.get(harmonized)
        if role is ActorRole.submitter and AUTHOR_COSIGNER_RE.search(verbatim):
            role = ActorRole.co_signatory
        name = c.get("fullname")
        if harmonized == "Author" and role is ActorRole.submitter and verbatim and not AUTHOR_SUBMITTER_RE.search(verbatim):
            flags.append(f"ambiguous_role:{verbatim}")  # keep the person, do not guess the role
            if name:
                out.append(Actor(name=_meta(name), role=Value(status="not_found")))
            continue
        if role is None or not name:
            flags.append(f"unmapped_role:{harmonized or verbatim or 'none'}")
            continue
        party = pick(c.get("party"), lang)
        out.append(Actor(name=_meta(name), role=_meta(role), party=_meta(party) if party else None))
    return out


def _history(a: dict, lang: str, flags: list[str]) -> list[ProceduralEvent]:
    out = []
    for e in sorted((a.get("events") or {}).get("data", []), key=lambda e: e.get("date") or ""):
        label = pick(e.get("title"), lang) or pick(e.get("title_harmonized"), lang)
        state = EVENT_TO_PROCEDURAL_STATE.get(e.get("title_harmonized_id"))
        if state is None:
            flags.append(f"unmapped_event:{label}")
            continue
        out.append(ProceduralEvent(date=_meta(_date(e.get("date"))), event=_meta(label), state=_meta(state)))
    if not any(ev.state.value == ProceduralState.submitted for ev in out) and _date(a.get("begin_date")):
        out.insert(0, ProceduralEvent(date=_meta(_date(a["begin_date"])), event=_meta("begin_date"),
                                      state=_meta(ProceduralState.submitted)))
    return out


def _refs(parsed: ParsedDoc | None, segments: SegmentResult | None):
    blocks: list[Block] = parsed.blocks if parsed else []
    annex_ids = set((segments.sections.get("annex") if segments else None) or [])
    ref = lambda b, cap=None: Reference(page=b.page, caption=cap, block_id=b.id)
    return ([ref(b, b.text.strip()) for b in blocks if b.id in annex_ids and b.type == "heading"],
            [ref(b) for b in blocks if b.type == "table"], [ref(b) for b in blocks if b.type == "image"])


def _first(history: list[ProceduralEvent], state: ProceduralState, last: bool = False) -> date | None:
    ds = [e.date.value for e in history if e.state.value == state and e.date.value]
    return (ds[-1] if last else ds[0]) if ds else None


def merge_affair(affair_json: dict, manifest: dict, parsed: ParsedDoc | None, segments: SegmentResult | None,
                 verified: VerifiedParts | None, body: dict | None = None, disagreement_log: Path | None = None,
                 extra_flags: list[str] | None = None) -> Affair:
    a = affair_json
    own: list[str] = []
    source = _source(a, manifest, parsed, body, own)
    lang = source.language.value
    own += [f"relation_truncated:{r}" for r in ("docs", "events", "contributors")
            if ((a.get(r) or {}).get("meta") or {}).get("has_more")]
    type_label = pick(a.get("type_name"), lang) or pick(a.get("type_harmonized"), lang)
    affair = Affair(
        source=source,
        affair_type=_meta(HARMONIZED_TYPE_TO_AFFAIR_TYPE.get(a.get("type_harmonized_id"), AffairType.other)),
        original_type_label=_meta(type_label),
        reference_number=_meta(a.get("number")), title=_meta(pick(a.get("title"), lang)),
        actors=_actors(a, lang, own), addressed_body=addressed_body(parsed, segments),
        procedural_history=_history(a, lang, own))
    affair.annexes, affair.tables, affair.images = _refs(parsed, segments)
    if verified is None:
        own.append("no_extraction")
    else:
        for f in ("affair_text", "justification", "executive_reasoning", "questions", "answers", "decision"):
            setattr(affair, f, getattr(verified, f))
        own += _cross_check(affair, verified, a, disagreement_log, own)
    hist = affair.procedural_history
    decided = _first(hist, ProceduralState.decided, last=True) or (
        verified.decision.date.value if verified and verified.decision else None)
    own += check_date_order(_first(hist, ProceduralState.submitted), _first(hist, ProceduralState.answered), decided)
    parts = [verified.review_flags if verified else [], segments.review_flags if segments else [],
             parsed.review_flags if parsed else [], manifest.get("flags", []), extra_flags or [], own]
    affair.review_flags = list(dict.fromkeys(f for p in parts for f in p))
    return affair


def _cross_check(affair: Affair, verified: VerifiedParts, a: dict, log: Path | None, own: list[str]) -> list[str]:
    """Metadata vs extraction. Returns flags; appends one JSON line per disagreement to `log`."""
    hist, flags, rows = affair.procedural_history, [], []
    dec = verified.decision
    meta_dec = _first(hist, ProceduralState.decided, last=True)
    if dec and dec.date.value and meta_dec and dec.date.value != meta_dec:
        block = dec.date.provenance[0].block_id if dec.date.provenance else None
        rows.append(("decision.date", meta_dec.isoformat(), dec.date.value.isoformat(), block))
    meta_ans = _first(hist, ProceduralState.answered) is not None
    ext_ans = any(x.text.value for x in verified.answers)
    real = [e for e in hist if e.event.value != "begin_date"]  # drop the synthesized submitted event
    unmapped = any(f.startswith("unmapped_event:") for f in own)
    # missing metadata is not a claim of "not answered": only compare when it can speak for itself
    if (meta_ans and not ext_ans) or (not meta_ans and ext_ans and real and not unmapped):
        rows.append(("answered", meta_ans, ext_ans, None))
    for field, meta, ext, block in rows:
        flags.append(f"disagreement:{field}")
        if log:
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with Path(log).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"affair_id": str(a["id"]), "field": field, "metadata_value": meta,
                                     "extracted_value": ext, "block_id": block}, ensure_ascii=False) + "\n")
    return flags
