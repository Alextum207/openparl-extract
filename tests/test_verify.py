from datetime import date

from openparl_extract.extract.schemas import (
    ExtractedAnswer, ExtractedDecision, ExtractedItem, ExtractedQuestion, ExtractionResult)
from openparl_extract.models import DecisionOutcome
from openparl_extract.parse.blocks import Block
from openparl_extract.verify.verify import check_date_order, locate, verify, verify_item

B1 = Block(id="p1_b0", page=1, text="Der Regierungsrat beantragt die Ablehnung der Motion.")
B2 = Block(id="p2_b0", page=2, text="Der Verwaltungs-\nrat   hat   am 3.5.2024 beschlossen.")
B3 = Block(id="p3_b0", page=3, text="Le Conseil d’Etat répond à l’interpellation. Èpoque à Zürich, città: perché.")
BLOCKS = [B1, B2, B3]
BY_ID = {b.id: b for b in BLOCKS}


def item(value, block_id, quote):
    return ExtractedItem(value=value, block_id=block_id, quote=quote)


def test_exact_quote_offsets():
    v, flags = verify_item(item("Ablehnung der Motion", "p1_b0", "Ablehnung der Motion"), BY_ID, 90)
    p = v.provenance[0]
    assert v.status == "extracted" and not flags and p.page == 1
    assert B1.text[p.char_start:p.char_end] == p.quote == "Ablehnung der Motion"


def test_hyphenation_and_whitespace_maps_to_original():
    v, _ = verify_item(item("Verwaltungsrat hat", "p2_b0", "Verwaltungsrat hat"), BY_ID, 90)
    p = v.provenance[0]
    assert v.status == "extracted"
    assert p.quote == B2.text[p.char_start:p.char_end]
    assert p.quote == "Verwaltungs-\nrat   hat"
    # model quote with hyphen/newline, extra whitespace, other case
    v2, _ = verify_item(item("verwaltungsrat hat", "p2_b0", "Verwaltungs-\nrat hat"), BY_ID, 90)
    assert v2.status == "extracted"


def test_soft_hyphen():
    b = Block(id="p9_b0", page=9, text="Verwal­tungsrat tagt")
    v, _ = verify_item(item("Verwaltungsrat", "p9_b0", "Verwaltungsrat"), {"p9_b0": b}, 90)
    p = v.provenance[0]
    assert v.status == "extracted" and b.text[p.char_start:p.char_end] == p.quote


def test_hallucinated_quote():
    v, flags = verify_item(item("Der Bundesrat lehnt ab", "p1_b0", "Der Bundesrat lehnt alles ab, ganz klar"), BY_ID, 90)
    assert v.value is None and v.status == "not_found"
    assert flags == ["quote_not_found:p1_b0"] and v.review_flag == flags[0]


def test_unknown_block_and_missing_quote():
    v, flags = verify_item(item("x", "p99_b9", "x"), BY_ID, 90)
    assert v.status == "not_found" and flags == ["block_not_found:p99_b9"]
    v, flags = verify_item(item("x", None, "x"), BY_ID, 90)
    assert flags == ["block_not_found:None"]
    v, flags = verify_item(item("Ablehnung", "p1_b0", None), BY_ID, 90)
    assert v.status == "not_found" and flags == ["missing_quote"]


def test_paraphrased_value_not_supported():
    v, flags = verify_item(item("Der Rat will die Motion annehmen", "p1_b0", "beantragt die Ablehnung der Motion"), BY_ID, 90)
    assert v.status == "not_found" and flags == ["value_not_supported"]


def test_absent_item_no_flag():
    for it in (None, ExtractedItem()):
        v, flags = verify_item(it, BY_ID, 90)
        assert v.status == "not_found" and v.value is None and flags == []


def test_french_italian_accents_apostrophes():
    v, _ = verify_item(item("Le Conseil d'Etat répond à l'interpellation", "p3_b0",
                            "Le Conseil d'Etat répond à l'interpellation"), BY_ID, 90)
    p = v.provenance[0]
    assert v.status == "extracted" and B3.text[p.char_start:p.char_end] == p.quote
    assert "’" in p.quote  # original text kept, not the model's quote
    v, _ = verify_item(item("Zürich, città: perché", "p3_b0", "zürich, città: perché"), BY_ID, 90)
    assert v.status == "extracted"


def test_threshold_honoured():
    near = "Der Regierungsrat beantragt die Ablehnng der Motion"  # one typo
    v, _ = verify_item(item(near, "p1_b0", near), BY_ID, 90)
    assert v.status == "extracted"
    v, flags = verify_item(item(near, "p1_b0", near), BY_ID, 100)
    assert v.status == "not_found" and flags == ["quote_not_found:p1_b0"]


def _dec(outcome, date_, quote="beschlossen", body=None):
    return ExtractionResult(decision=ExtractedDecision(
        outcome=ExtractedItem(value=outcome, block_id="p2_b0", quote=quote) if outcome else ExtractedItem(),
        date=ExtractedItem(value=date_, block_id="p2_b0", quote="am 3.5.2024 beschlossen") if date_ else ExtractedItem(),
        body=body or ExtractedItem()))


def test_outcome_vocab():
    for raw in ("adopted", " Partially Adopted ", "referred-to-executive"):
        d = verify(_dec(raw, None), BLOCKS).decision
        assert d.outcome.status == "extracted"
    assert verify(_dec("Partially Adopted", None), BLOCKS).decision.outcome.value == DecisionOutcome.partially_adopted
    r = verify(_dec("Abgelehnt", None), BLOCKS)
    assert r.decision.outcome.status == "not_found" and "vocab_invalid:outcome:Abgelehnt" in r.review_flags


def test_outcome_needs_real_quote():
    r = verify(_dec("adopted", None, quote="erfunden und nicht im Text vorhanden"), BLOCKS)
    assert r.decision.outcome.status == "not_found" and "quote_not_found:p2_b0" in r.review_flags


def test_decision_date():
    r = verify(_dec(None, "2024-05-03"), BLOCKS)
    assert r.decision.date.value == date(2024, 5, 3) and r.decision.date.status == "extracted"
    r = verify(_dec(None, "3.5.2024"), BLOCKS)
    assert r.decision.date.value == date(2024, 5, 3)
    r = verify(_dec(None, "dritter Mai"), BLOCKS)
    assert r.decision.date.status == "not_found" and "date_unparseable" in r.review_flags
    r = verify(_dec(None, "2024-06-01"), BLOCKS)  # parses, but the quote says 3.5.2024
    assert r.decision.date.status == "not_found" and "value_not_supported" in r.review_flags


def test_decision_all_not_found_is_still_decision():
    r = verify(_dec(None, None), BLOCKS)
    assert r.decision is not None and r.decision.outcome.status == "not_found"
    assert verify(ExtractionResult(), BLOCKS).decision is None


def q(i, text="Ablehnung der Motion"):
    return ExtractedQuestion(id=i, text=item(text, "p1_b0", text))


def a(qid, text="Ablehnung der Motion"):
    return ExtractedAnswer(question_id=qid, text=item(text, "p1_b0", text))


def test_duplicate_question_ids():
    r = verify(ExtractionResult(questions=[q("1"), q("1"), q("2")], answers=[a("1"), a("2")]), BLOCKS)
    assert len(r.questions) == 3
    assert "duplicate_question_id:1" in r.review_flags
    assert r.answers[0].question_id is None and "answer_ambiguous_question:1" in r.review_flags
    assert r.answers[1].question_id == "2"


def test_answer_unknown_question():
    r = verify(ExtractionResult(questions=[q("1")], answers=[a("7")]), BLOCKS)
    assert r.answers[0].question_id is None and "answer_unknown_question:7" in r.review_flags


def test_multiple_answers_kept():
    r = verify(ExtractionResult(questions=[q("1")], answers=[a("1"), a("1")]), BLOCKS)
    assert len(r.answers) == 2 and r.answers[0].question_id == "1"
    assert r.review_flags.count("multiple_answers:1") == 1
    assert r.answers[0].text.review_flag is None
    assert r.answers[1].text.review_flag == "multiple_answers:1"
    r = verify(ExtractionResult(questions=[q("1")], answers=[a("1"), a("1"), a("1")]), BLOCKS)
    assert [x.text.review_flag for x in r.answers] == [None, "multiple_answers:1", "multiple_answers:1"]


def test_structural_flag_joined_with_item_flag():
    # review_flag holds all flags of that value joined with ';'
    bad = ExtractedAnswer(question_id="7", text=item("zzz", "p1_b0", "zzz zzz zzz zzz"))
    r = verify(ExtractionResult(questions=[q("1")], answers=[bad]), BLOCKS)
    assert r.answers[0].text.review_flag == "quote_not_found:p1_b0;answer_unknown_question:7"


def test_value_with_invented_extra_text_rejected():
    v, flags = verify_item(item("Der Regierungsrat beantragt die Ablehnung der Motion. Er will zudem 5 Mio. Franken sprechen.",
                                "p1_b0", "Ablehnung der Motion"), BY_ID, 90)
    assert v.status == "not_found" and flags == ["value_not_supported"]
    v, flags = verify_item(item("Der Rat lehnt die Motion ab und kritisiert die SVP scharf", "p1_b0", "Motion"), BY_ID, 90)
    assert v.status == "not_found" and flags == ["value_not_supported"]


def test_quote_longer_than_block_rejected():
    b = {"p1_b0": Block(id="p1_b0", page=1, text="Ja.")}
    t = "Ja. Der Regierungsrat lehnt die Motion vollumfaenglich ab."
    v, flags = verify_item(item(t, "p1_b0", t), b, 90)
    assert v.status == "not_found" and v.value is None and flags == ["quote_not_found:p1_b0"]


def test_fuzzy_span_trimmed():
    b = Block(id="p1_b0", page=1, text="xx die Ablehnung der Motion folgt")
    s, e = locate("die Ablehnug der Motion", b, 90)
    got = b.text[s:e]
    assert got == got.strip() and "Ablehnung der Motion" in got


def test_failed_question_stays():
    r = verify(ExtractionResult(questions=[ExtractedQuestion(id="1", text=item("zzz", "p1_b0", "zzz zzz zzz zzz"))]), BLOCKS)
    assert r.questions[0].id == "1" and r.questions[0].text.status == "not_found"
    assert r.questions[0].text.review_flag in r.review_flags


def test_check_date_order():
    d = date
    assert check_date_order(d(2024, 1, 1), d(2024, 2, 1), d(2024, 3, 1)) == []
    assert check_date_order(d(2024, 3, 1), d(2024, 2, 1), None) == ["date_order:submitted_after_answered"]
    assert check_date_order(None, d(2024, 3, 1), d(2024, 2, 1)) == ["date_order:answered_after_decided"]
    assert check_date_order(d(2024, 3, 1), None, d(2024, 2, 1)) == ["date_order:submitted_after_decided"]
    assert check_date_order(None, None, None) == []


def test_happy_path_and_flags_collected():
    res = ExtractionResult(
        affair_text=item("Der Regierungsrat beantragt die Ablehnung der Motion.", "p1_b0",
                         "Der Regierungsrat beantragt die Ablehnung der Motion."),
        justification=item("erfunden", "p1_b0", "Kein solcher Text"),
        questions=[q("1")], answers=[a("1")],
        decision=_dec("adopted", "3.5.2024").decision,
        prompt_versions={"questions": "v1"})
    r = verify(res, BLOCKS)
    assert r.affair_text.status == "extracted" and r.justification.status == "not_found"
    assert r.executive_reasoning.status == "not_found"
    assert r.prompt_versions == {"questions": "v1"}
    assert r.review_flags == ["quote_not_found:p1_b0"]
    assert r.justification.review_flag == "quote_not_found:p1_b0"
    assert r.decision.outcome.status == "extracted" and r.decision.date.status == "extracted"


def test_empty_result_never_raises():
    r = verify(ExtractionResult(), [])
    assert r.review_flags == [] and r.questions == [] and r.affair_text.status == "not_found"


def test_verify_copies_extract_errors_into_review_flags():
    r = ExtractionResult(errors=["client_error:questions:TimeoutError"])
    assert "extract_error:client_error:questions:TimeoutError" in verify(r, BLOCKS).review_flags
