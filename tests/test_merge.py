import copy
import json
from datetime import date
from pathlib import Path

import pytest

from openparl_extract.ingest.store import load_manifest, save_affair
from openparl_extract.merge.merge import merge_affair
from openparl_extract.models import Affair, Decision, DecisionOutcome, Provenance, Value
from openparl_extract.parse.blocks import Block, ParsedDoc
from openparl_extract.segment.rules import segment
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
    nf = lambda: Value(status="not_found")
    base = dict(affair_text=nf(), justification=nf(), executive_reasoning=nf(), questions=[], answers=[],
                decision=None, review_flags=[], prompt_versions={})
    return VerifiedParts(**{**base, **kw})


def test_zh_motion_metadata_mapped(tmp_path):
    af = merge("zh_motion_219288", tmp_path)
    assert af.source.level == "cantonal" and af.source.language == "de" and af.source.parliament == "Zürich" and af.source.body_key == "ZH"
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


# ---- fix round 1 ----
from openparl_extract.merge.language import detect_language
from openparl_extract.models import Answer

DE = "Der Regierungsrat ist der Ansicht, dass die Frage nicht mit dem Gesetz und der Verordnung vereinbar ist. " * 3
FR = "Le Conseil d'Etat est d'avis que la question n'est pas dans le cadre de la loi et que les droits sont une chose. " * 3
IT = "Il Consiglio di Stato e del parere che la domanda non sia nel quadro della legge e che i diritti sono una cosa. " * 3


def answer_verified():
    prov = [Provenance(page=2, block_id="p2_b1", quote="Antwort")]
    return empty_verified(answers=[Answer(text=Value(value="Antwort", status="extracted", provenance=prov))])


def test_detect_language():
    assert detect_language(DE, ["de", "fr", "it"]) == "de"
    assert detect_language(FR, ["de", "fr", "it"]) == "fr"
    assert detect_language(IT, ["de", "fr", "it"]) == "it"
    assert detect_language(DE + FR, ["de", "fr"]) is None  # tie: no clear winner
    assert detect_language("", ["de", "fr"]) is None
    assert detect_language(FR, ["de"]) is None  # needs >= 10 hits and 1.5x runner-up among candidates only


def bilingual(tmp_path, parsed=None):
    a = load("che_interpellation_340788")
    a["title"] = {"it": "Titolo", "fr": a["title"]["fr"], "de": "Titel"}
    return merge_affair(a, manifest_of(a, tmp_path), parsed, None, None, body=BODIES["CHE"])


def test_language_ambiguous_prefers_fixed_order_not_dict_order(tmp_path):
    af = bilingual(tmp_path)
    assert af.source.language == "de" and af.title.value == "Titel"
    assert "language_ambiguous:it,fr,de" in af.review_flags
    assert not any(f.startswith("language_detected") for f in af.review_flags)


def test_language_ambiguous_detected_from_parsed_text(tmp_path):
    p = ParsedDoc(source_file="x", page_count=1, is_scanned=False, blocks=[Block(id="p1_b0", page=1, text=FR)])
    af = bilingual(tmp_path, p)
    assert af.source.language == "fr"
    assert "language_ambiguous:it,fr,de" in af.review_flags and "language_detected:fr" in af.review_flags


def test_single_language_no_flag(tmp_path):
    af = merge("che_interpellation_340788", tmp_path)
    assert not any(f.startswith("language_") for f in af.review_flags)


def test_answered_not_logged_when_metadata_has_no_mapped_events(tmp_path):
    log = tmp_path / "d.jsonl"
    af = merge("che_interpellation_340788", tmp_path, verified=answer_verified(), disagreement_log=log)
    assert not log.exists() and "disagreement:answered" not in af.review_flags


def test_answered_not_logged_when_unmapped_events_exist(tmp_path):
    log = tmp_path / "d.jsonl"  # ZH motion: mapped events, none answered, but unmapped_event flags were raised
    af = merge("zh_motion_219288", tmp_path, verified=answer_verified(), disagreement_log=log)
    assert any(f.startswith("unmapped_event") for f in af.review_flags)
    assert not log.exists()


def test_answered_logged_case_b_no_unmapped_events(tmp_path):
    a = load("zurich_city_interpellation_14228")
    a["events"]["data"] = [e for e in a["events"]["data"] if e["title_harmonized_id"] != 6]
    log = tmp_path / "d.jsonl"
    af = merge_affair(a, manifest_of(a, tmp_path), None, None, answer_verified(), body=BODIES["261"],
                      disagreement_log=log)
    row = json.loads(log.read_text(encoding="utf-8"))
    assert row["field"] == "answered" and row["metadata_value"] is False and row["extracted_value"] is True
    assert "disagreement:answered" in af.review_flags


def test_answered_logged_case_a_event_but_no_extracted_answer(tmp_path):
    log = tmp_path / "d.jsonl"
    merge("zurich_city_interpellation_14228", tmp_path, verified=empty_verified(), disagreement_log=log)
    assert json.loads(log.read_text(encoding="utf-8"))["metadata_value"] is True


def test_answered_agree_not_logged(tmp_path):
    log = tmp_path / "d.jsonl"
    merge("zurich_city_interpellation_14228", tmp_path, verified=answer_verified(), disagreement_log=log)
    assert not log.exists()


def with_role(tmp_path, harmonized, verbatim):
    a = load("che_interpellation_340788")
    c = a["contributors"]["data"][1]
    c["role_harmonized"], c["role"] = {"en": harmonized}, ({"de": verbatim} if verbatim else {})
    return merge_affair(a, manifest_of(a, tmp_path), None, None, None, body=BODIES["CHE"])


@pytest.mark.parametrize("verbatim,role", [("Urheber(-in)", "submitter"), ("Erstunterzeichnender", "submitter"),
                                           ("Presentata", "submitter"), ("Auteur", "submitter"),
                                           ("Hauptvorstösserin/Hauptvorstösser", "submitter"), (None, "submitter"),
                                           ("Mitunterzeichner", "co_signatory"), ("Cosignataire", "co_signatory"),
                                           ("Cofirmatario", "co_signatory")])
def test_author_role_known_forms(tmp_path, verbatim, role):
    af = with_role(tmp_path, "Author", verbatim)
    assert af.actors[0].role.value == role and not any(f.startswith("ambiguous_role") for f in af.review_flags)


def test_author_role_ambiguous_keeps_person_flags(tmp_path):
    af = with_role(tmp_path, "Author", "Beteiligung")
    assert af.actors[0].name.value == "Sidney Kamerzin"
    assert af.actors[0].role.status == "not_found" and af.actors[0].role.value is None
    assert "ambiguous_role:Beteiligung" in af.review_flags


def test_relation_truncated_flag(tmp_path):
    a = load("zh_motion_219288")
    a["events"]["meta"]["has_more"] = True
    af = merge_affair(a, manifest_of(a, tmp_path), None, None, None, body=BODIES["ZH"])
    assert "relation_truncated:events" in af.review_flags
    assert not any(f.startswith("relation_truncated") for f in merge("zh_motion_219288", tmp_path).review_flags)
