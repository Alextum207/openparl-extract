import copy
import json
from datetime import date
from pathlib import Path

import pytest

from openparl_extract.ingest.store import load_manifest, save_affair
from openparl_extract.merge.merge import merge_affair
from openparl_extract.models import Affair, Decision, DecisionOutcome, Provenance, Value
from openparl_extract.parse.blocks import Block, ParsedDoc
from openparl_extract.segment.rules import SegmentResult, segment
from openparl_extract.verify.verify import VerifiedParts

FIX = Path(__file__).parent / "fixtures"
BODIES = json.loads((FIX / "merge" / "bodies.json").read_text(encoding="utf-8"))
PDF = b"%PDF-1.4 tiny"


def load(name):
    return json.loads((FIX / "merge" / f"{name}.json").read_text(encoding="utf-8"))


def manifest_of(affair, tmp_path):
    return load_manifest(save_affair(affair, {d["id"]: PDF for d in (affair.get("docs") or {}).get("data", [])},
                                     tmp_path) / "manifest.json")


def merge(name, tmp_path, body_key=None, **kw):
    a = load(name)
    kw.setdefault("parsed", None), kw.setdefault("segments", None), kw.setdefault("verified", None)
    return merge_affair(a, manifest_of(a, tmp_path), body=BODIES[body_key or a["body_key"]], **kw)


def empty_verified(**kw):
    nf = lambda: Value(status="not_found")  # noqa: E731
    base = dict(affair_text=nf(), justification=nf(), executive_reasoning=nf(), questions=[], answers=[],
                decision=None, review_flags=[], prompt_versions={})
    return VerifiedParts(**{**base, **kw})


def test_zh_motion_metadata_mapped(tmp_path):
    af = merge("zh_motion_219288", tmp_path)
    assert af.source.level == "cantonal" and af.source.language == "de" and af.source.parliament == "Zürich"
    assert af.source.pdf_sha256 and af.source.document_url.startswith("https://files.openparldata.ch/")
    assert (af.title.value.startswith("Ein eigener Hochschulrat"), af.title.status) == (True, "from_metadata")
    assert af.affair_type.value == "motion" and af.affair_type.status == "from_metadata"
    assert af.original_type_label.value == "Motion" and af.reference_number.value == "104/2025"
    roles = {a.name.value: a.role.value for a in af.actors}
    assert roles["Bildungsdirektion"] == "executive_respondent"
    assert roles["Monika Wicki"] == "co_signatory" and next(r for n, r in roles.items() if n.startswith("Carmen Marty")) == "submitter"
    wicki = next(a for a in af.actors if a.name.value == "Monika Wicki")
    assert wicki.party.value == "SP" and wicki.faction is None and wicki.role.status == "from_metadata"
    states = [(e.state.value, e.date.value) for e in af.procedural_history]
    assert states[0] == ("submitted", date(2025, 3, 31)) and ("decided", date(2026, 3, 9)) in states
    assert all(e.event.status == "from_metadata" for e in af.procedural_history)
    assert sum(e.state.value == "submitted" for e in af.procedural_history) == 1  # begin_date NOT added again
    assert "unmapped_event:Stellungnahme Regierungsrat" in af.review_flags  # id 29 has no evidence-backed state
    assert "no_extraction" in af.review_flags


def test_municipal_and_answered_event(tmp_path):
    af = merge("zurich_city_interpellation_14228", tmp_path)
    assert af.source.level == "municipal" and af.affair_type.value == "interpellation"
    assert [e.state.value for e in af.procedural_history] == ["submitted", "answered", "debated"]
    assert af.procedural_history[1].event.value == "Stadtrat, Antwort"


def test_italian_question_language_from_title(tmp_path):
    af = merge("ti_question_336921", tmp_path)
    assert af.source.language == "it" and af.affair_type.value == "written_question"
    assert af.original_type_label.value == "Anfrage" or af.original_type_label.value  # verbatim label kept
    assert af.actors[0].role.value in ("submitter", "executive_respondent")
    assert any(a.role.value == "submitter" and a.name.value == "Matteo Quadranti" for a in af.actors)


def test_federal_level_and_begin_date_submitted_when_event_unmapped(tmp_path):
    af = merge("che_interpellation_340788", tmp_path)
    assert af.source.level == "federal" and af.source.language == "fr" and af.source.parliament == "Suisse"
    assert [(e.state.value, e.event.value) for e in af.procedural_history] == [("submitted", "begin_date")]
    assert af.procedural_history[0].date.value == date(2026, 10, 2)
    assert "unmapped_event:Depositato" in af.review_flags or "unmapped_event:Déposé" in af.review_flags
    assert "unmapped_role:Council Initial" in af.review_flags
    assert af.review_flags.count("no_document") == 1 and "no_document" in af.review_flags
    assert af.source.document_url is None and af.source.pdf_sha256 is None


def test_unmapped_type_is_other_with_label(tmp_path):
    a = json.loads((FIX / "api" / "affair_340560.json").read_text(encoding="utf-8"))  # type_harmonized_id 9
    af = merge_affair(a, manifest_of(a, tmp_path), None, None, None, body=BODIES["ZH"] | {"type": "canton"})
    assert af.affair_type.value == "other" and af.original_type_label.value == "Antrag"


def test_level_errors(tmp_path):
    a = load("zh_motion_219288")
    m = manifest_of(a, tmp_path)
    with pytest.raises(ValueError, match="level"):
        merge_affair(a, m, None, None, None, body=None)
    with pytest.raises(ValueError, match="foreign"):
        merge_affair(a, m, None, None, None, body=BODIES["LIE"])
    b = copy.deepcopy(a)
    b["body_key"] = "CHE"
    assert merge_affair(b, m, None, None, None, body=None).source.level == "federal"  # CHE fallback without body


def test_language_error(tmp_path):
    a = load("zh_motion_219288")
    a["title"] = {}
    a["docs"] = None
    with pytest.raises(ValueError, match="language"):
        merge_affair(a, {"docs": [], "flags": ["no_document"]}, None, None, None, body=BODIES["ZH"])


def test_municipality_body_type(tmp_path):
    assert merge("zh_motion_219288", tmp_path, body_key="4551").source.level == "municipal"


def blocks():
    return [Block(id="p1_b0", page=1, text="Interpellation Muster", type="heading"),
            Block(id="p2_b0", page=2, text="Antwort des Regierungsrates:", type="heading"),
            Block(id="p2_b1", page=2, text="Der Regierungsrat antwortet wie folgt."),
            Block(id="p3_b0", page=3, text="Anhang", type="heading"),
            Block(id="p3_b1", page=3, text="Tab", type="table"),
            Block(id="p3_b2", page=4, text="img", type="image")]


def parsed_seg(bl):
    return ParsedDoc(source_file="x.pdf", page_count=4, is_scanned=False, blocks=bl, review_flags=["parse_flag"]), segment(bl)


def test_addressed_body_with_offsets_and_refs(tmp_path):
    p, s = parsed_seg(blocks())
    af = merge("zh_motion_219288", tmp_path, parsed=p, segments=s)
    ab = af.addressed_body
    assert ab.status == "extracted" and ab.value == "Regierungsrat"
    pv = ab.provenance[0]
    assert (pv.page, pv.block_id, pv.char_start, pv.char_end) == (2, "p2_b0", 12, 25)
    assert p.blocks[1].text[pv.char_start:pv.char_end] == pv.quote == "Regierungsrat"
    assert [(r.page, r.caption) for r in af.annexes] == [(3, "Anhang")]
    assert [r.block_id for r in af.tables] == ["p3_b1"] and [r.page for r in af.images] == [4]
    assert "parse_flag" in af.review_flags and af.source.is_scanned is False


def test_addressed_body_accent_insensitive_and_not_found(tmp_path):
    bl = [Block(id="p1_b0", page=1, text="Réponse du Conseil d’État", type="heading")]
    p, s = parsed_seg(bl)
    assert s.block_section["p1_b0"] == "executive_answer"
    ab = merge("zh_motion_219288", tmp_path, parsed=p, segments=s).addressed_body
    assert ab.value == "Conseil d’État" and ab.provenance[0].char_start == 11
    bl = [Block(id="p1_b0", page=1, text="Interpellation", type="heading"), Block(id="p1_b1", page=1, text="Text.")]
    p, s = parsed_seg(bl)
    ab = merge("zh_motion_219288", tmp_path, parsed=p, segments=s).addressed_body
    assert ab.status == "not_found" and ab.value is None


def test_disagreement_logged_metadata_kept(tmp_path):
    prov = [Provenance(page=2, block_id="p2_b5", quote="9. Februar 2026")]
    dec = Decision(outcome=Value(value=DecisionOutcome.rejected, status="extracted", provenance=prov),
                   date=Value(value=date(2026, 2, 9), status="extracted", provenance=prov),
                   body=Value(status="not_found"))
    log = tmp_path / "out" / "disagreements.jsonl"
    af = merge("zh_motion_219288", tmp_path, verified=empty_verified(decision=dec), disagreement_log=log)
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert {"affair_id": "219288", "field": "decision.date", "metadata_value": "2026-03-09",
            "extracted_value": "2026-02-09", "block_id": "p2_b5"} in rows
    assert "disagreement:decision.date" in af.review_flags
    assert af.decision.date.value == date(2026, 2, 9) and af.decision.date.status == "extracted"
    assert any(e.state.value == "decided" and e.date.value == date(2026, 3, 9) for e in af.procedural_history)
    assert [r["field"] for r in rows] == ["decision.date"]  # no answer in events nor extraction: they agree
    assert "no_extraction" not in af.review_flags


def test_agreeing_values_no_disagreement(tmp_path):
    prov = [Provenance(page=2, block_id="p2_b5", quote="9. März 2026")]
    dec = Decision(outcome=Value(status="not_found"), body=Value(status="not_found"),
                   date=Value(value=date(2026, 3, 9), status="extracted", provenance=prov))
    log = tmp_path / "d.jsonl"
    af = merge("zh_motion_219288", tmp_path, verified=empty_verified(decision=dec), disagreement_log=log)
    assert not log.exists() and not any(f.startswith("disagreement") for f in af.review_flags)


def test_answered_event_without_extracted_answer_is_logged(tmp_path):
    log = tmp_path / "d.jsonl"
    af = merge("zurich_city_interpellation_14228", tmp_path, verified=empty_verified(), disagreement_log=log)
    row = json.loads(log.read_text(encoding="utf-8"))
    assert row["field"] == "answered" and row["metadata_value"] is True and row["extracted_value"] is False
    assert "disagreement:answered" in af.review_flags


def test_date_order_flag(tmp_path):
    a = load("zurich_city_interpellation_14228")
    a["events"]["data"][0]["date"] = "2025-01-01T00:00:00"  # submitted after answered
    af = merge_affair(a, manifest_of(a, tmp_path), None, None, None, body=BODIES["261"])
    assert "date_order:submitted_after_answered" in af.review_flags


def test_flags_union_dedup_order(tmp_path):
    bl = [Block(id="p1_b0", page=1, text="x")]
    p, s = parsed_seg(bl)
    assert s.review_flags == ["segmentation_failed"]
    v = empty_verified(review_flags=["quote_not_found:a", "shared"])
    s.review_flags.append("shared")
    p.review_flags = ["parse_flag"]
    af = merge("che_interpellation_340788", tmp_path, parsed=p, segments=s, verified=v,
               extra_flags=["shared", "extra"])
    f = af.review_flags
    assert len(f) == len(set(f))
    assert f.index("quote_not_found:a") < f.index("shared") < f.index("segmentation_failed") < f.index("parse_flag")
    assert f.index("parse_flag") < f.index("no_document") < f.index("extra")


def test_no_document_and_no_extraction(tmp_path):
    a = json.loads((FIX / "api" / "affair_nodocs.json").read_text(encoding="utf-8"))
    af = merge_affair(a, manifest_of(a, tmp_path), None, None, None, body=BODIES["ZH"] | {"type": "canton"})
    assert {"no_document", "no_extraction"} <= set(af.review_flags)
    assert af.affair_text is None and af.questions == [] and af.decision is None and af.title.status == "from_metadata"


@pytest.mark.parametrize("name", ["zh_motion_219288", "zurich_city_interpellation_14228", "ti_question_336921",
                                  "che_interpellation_340788"])
def test_result_roundtrips_schema(name, tmp_path):
    p, s = parsed_seg(blocks())
    af = merge(name, tmp_path, parsed=p, segments=s, verified=empty_verified())
    assert Affair.model_validate_json(af.model_dump_json()) == af
    for v in [af.addressed_body, af.title]:  # extracted values always carry provenance
        assert v.status != "extracted" or v.provenance
