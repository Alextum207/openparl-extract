from openparl_extract.parse.blocks import Block
from openparl_extract.segment.rules import (
    SECTIONS,
    SegmentResult,
    section_blocks,
    segment,
)


def mk(*items):
    """items: (text, type) or text -> Blocks with ids p1_b0..."""
    out = []
    for i, it in enumerate(items):
        text, typ = (it, "paragraph") if isinstance(it, str) else it
        out.append(Block(id=f"p1_b{i}", page=1, text=text, type=typ))
    return out


def sec(r, name):
    return r.sections[name]


def test_german():
    b = mk(("Interpellation", "heading"), "Der Regierungsrat wird gebeten...",
           ("Begründung", "heading"), "Weil ...",
           ("Fragen", "heading"), "1. Wie viele?",
           ("Antwort des Regierungsrates", "heading"), "Der Regierungsrat antwortet.",
           ("Beschluss", "heading"), "Der Grosse Rat nimmt Kenntnis.",
           ("Anhang", "heading"), "Tabelle")
    r = segment(b)
    assert sec(r, "affair_text") == ["p1_b0", "p1_b1"]
    assert sec(r, "justification") == ["p1_b2", "p1_b3"]
    assert sec(r, "questions") == ["p1_b4", "p1_b5"]
    assert sec(r, "executive_answer") == ["p1_b6", "p1_b7"]
    assert sec(r, "decision") == ["p1_b8", "p1_b9"]
    assert sec(r, "annex") == ["p1_b10", "p1_b11"]
    assert r.review_flags == []
    assert r.block_section["p1_b7"] == "executive_answer"
    assert ("p1_b6", "executive_answer") in r.headings


def test_french():
    b = mk(("Interpellation", "heading"), "texte", ("Développement", "heading"), "x",
           ("Questions", "heading"), "q", ("Réponse du Conseil d'Etat", "heading"), "r",
           ("Annexes", "heading"), "a")
    r = segment(b)
    assert [len(sec(r, s)) for s in ("affair_text", "justification", "questions", "executive_answer", "annex")] == [2] * 5


def test_italian():
    b = mk(("Interrogazione", "heading"), "testo", ("Motivazione", "heading"), "x",
           ("Domande", "heading"), "q", ("Risposta del Consiglio di Stato", "heading"), "r",
           ("Allegato", "heading"), "a", ("Decisione", "heading"), "d")
    r = segment(b)
    assert [len(sec(r, s)) for s in ("affair_text", "justification", "questions", "executive_answer", "annex", "decision")] == [2] * 6


def test_uppercase_accents_apostrophes_numbering():
    for t in ("ANTWORT DES REGIERUNGSRATES", "Reponse du Conseil d'Etat", "Réponse du Conseil d’Etat",
              "Réponse du Conseil d´État", "RÉPONSE DU CONSEIL D'ÉTAT", "2. Antwort des Regierungsrates:",
              "II. Antwort des Bundesrates", "A) Risposta del Consiglio di Stato", "2.1 Antwort"):
        r = segment(mk("vorher", (t, "heading"), "body"))
        assert sec(r, "executive_answer") == ["p1_b1", "p1_b2"], t


def test_long_paragraph_does_not_open():
    long = "Wir bedanken uns. Die Antwort des Regierungsrates auf diese Frage lautet wie folgt, und zwar " * 3
    r = segment(mk(("Begründung", "heading"), long, "mehr"))
    assert sec(r, "executive_answer") == []
    assert sec(r, "justification") == ["p1_b0", "p1_b1", "p1_b2"]


def test_short_paragraph_heading_without_type():
    r = segment(mk("text", "Antwort des Regierungsrates", "body"))
    assert sec(r, "executive_answer") == ["p1_b1", "p1_b2"]


def test_before_first_heading_is_affair_text():
    r = segment(mk("a", "b", ("Fragen", "heading"), "c"))
    assert sec(r, "affair_text") == ["p1_b0", "p1_b1"]
    assert sec(r, "questions") == ["p1_b2", "p1_b3"]


def test_annex_runs_until_next_heading():
    r = segment(mk(("Anhang", "heading"), "x", "y", ("Beschluss", "heading"), "z"))
    assert sec(r, "annex") == ["p1_b0", "p1_b1", "p1_b2"]
    assert sec(r, "decision") == ["p1_b3", "p1_b4"]


def test_two_answer_headings():
    r = segment(mk(("Antwort des Regierungsrates", "heading"), "a", ("Fragen", "heading"), "q",
                   ("Antwort des Regierungsrates", "heading"), "b"))
    assert sec(r, "executive_answer") == ["p1_b0", "p1_b1", "p1_b4", "p1_b5"]
    assert len(r.headings) == 3


def test_no_heading_all_other():
    r = segment(mk("alpha", "beta"))
    assert sec(r, "other") == ["p1_b0", "p1_b1"]
    assert "segmentation_failed" in r.review_flags
    assert r.block_section == {"p1_b0": "other", "p1_b1": "other"}


def test_empty_list():
    r = segment([])
    assert set(r.sections) == set(SECTIONS)
    assert all(v == [] for v in r.sections.values())
    assert isinstance(r, SegmentResult)


def test_image_table_stay_in_section():
    r = segment(mk(("Anhang", "heading"), ("t", "table"), ("", "image")))
    assert sec(r, "annex") == ["p1_b0", "p1_b1", "p1_b2"]


def test_section_blocks_helper():
    b = mk(("Fragen", "heading"), "q1", ("Antwort", "heading"), "a")
    r = segment(b)
    assert [x.id for x in section_blocks(r, b, "questions")] == ["p1_b0", "p1_b1"]


# --- fixtures built from real headings observed in OpenParlData PDFs (BE, ZH, FR, GE, TI) ---
def test_real_be_form_antrag_regierungsrat_is_not_a_decision():
    r = segment(mk(("Parlamentarischer Vorstoss", "heading"), "Vorstoss-Nr.:", "Antrag Regierungsrat:",
                   ("Kinderrechte im Nothilferegime sicher schützen", "heading"), "Begründung:", "text"))
    assert sec(r, "decision") == []
    assert sec(r, "justification") == ["p1_b4", "p1_b5"]


def test_real_zh_no_heading_questions_intro():
    r = segment(mk("KR-Nr. 362/2026", "Betreffend Rechnungslegung", "Hintergrundtext",
                   "Vor diesem Hintergrund ersuchen wir um Beantwortung folgender Fragen:", "Plant die GD ...?"))
    assert sec(r, "questions") == ["p1_b3", "p1_b4"]
    assert r.review_flags == []


def test_real_fr_fribourg_and_geneve():
    r = segment(mk(("Dépôt d'un instrument parlementaire", "heading"), "Postulat 2026-GC-246",
                   ("Dépôt et développement", "heading"), "texte",
                   ("EXPOSÉ DES MOTIFS", "heading"), "x", ("ANNEXE 1", "heading"), "y"))
    assert sec(r, "affair_text") == ["p1_b0", "p1_b1", "p1_b2", "p1_b3"]
    assert sec(r, "justification") == ["p1_b4", "p1_b5"]
    assert sec(r, "annex") == ["p1_b6", "p1_b7"]


def test_real_ti_interpellanza():
    r = segment(mk(("INTERPELLANZA (art. 97 LGC)", "heading"), "Presentata da: X",
                   ("Motivazione riguardo l'interesse pubblico e l'urgenza [cfr. art. 97 cpv. 3 LGC]", "heading"),
                   ("Testo:", "heading"), "Rileviamo", "Si chiede quindi al Consiglio di Stato:", "domanda"))
    # fix round 1: affair_text can no longer reopen after justification, so "Testo:" stays in justification
    assert sec(r, "justification") == ["p1_b2", "p1_b3", "p1_b4"]
    assert sec(r, "affair_text") == ["p1_b0", "p1_b1"]
    assert sec(r, "questions") == ["p1_b5", "p1_b6"]


# --- review fix round 1 ---
def test_anfrage_title_is_affair_text_not_questions():
    r = segment(mk("Anfrage Müller betreffend X", ("Fragen", "heading"), "q"))
    assert sec(r, "affair_text") == ["p1_b0"] and sec(r, "questions") == ["p1_b1", "p1_b2"]
    r = segment(mk("Anfrage Müller betreffend X", "text"))
    assert sec(r, "questions") == []


def test_affair_text_cannot_reopen_after_other_section():
    for t in ("Motion abgelehnt.", "Postulat", "Testo di legge"):
        for typ in ("paragraph", "heading"):
            r = segment(mk(("Beschluss", "heading"), (t, typ), "weiter"))
            assert sec(r, "decision") == ["p1_b0", "p1_b1", "p1_b2"], (t, typ)
            assert sec(r, "affair_text") == []


def test_bare_annex_word_in_sentence_stays():
    r = segment(mk(("Fragen", "heading"), "Anhang zum Bericht ist beigelegt.", "x"))
    assert sec(r, "annex") == [] and len(sec(r, "questions")) == 3
    r = segment(mk("vorher", ("Anhang", "heading"), "x"))
    assert sec(r, "annex") == ["p1_b1", "p1_b2"]
    r = segment(mk("vorher", "Anhang 1", "x"))  # short non-sentence line still opens
    assert sec(r, "annex") == ["p1_b1", "p1_b2"]


def test_bare_antwort_rules():
    long = "Antwort auf Frage 1 der Interpellation betreffend die Lage im Kanton"
    assert sec(segment(mk("v", long, "x")), "executive_answer") == []
    assert sec(segment(mk("v", (long, "heading"), "x")), "executive_answer") == ["p1_b1", "p1_b2"]
    assert sec(segment(mk("v", "Antwort auf Frage 1", "x")), "executive_answer") == ["p1_b1", "p1_b2"]
    assert sec(segment(mk("v", "Antwort des Regierungsrates zur Lage im Kanton und weiteres Vorgehen", "x")),
               "executive_answer") == ["p1_b1", "p1_b2"]


def test_letter_enumerators_and_spaced_headings():
    # Emmen: "A Wortlaut des Postulats" / "B Stellungnahme des Gemeinderates"
    b = mk(("A Wortlaut des Postulats", "heading"), "Der Gemeinderat wird beauftragt ...",
           ("B Stellungnahme des Gemeinderates", "heading"), "Der Gemeinderat beantragt ...")
    r = segment(b)
    assert "segmentation_failed" not in r.review_flags
    assert sec(r, "executive_answer") == ["p1_b2", "p1_b3"]
    # spaced capitals must still match as before (single letters are not enumerators)
    assert segment(mk(("A N F R A G E", "heading"), "Text")).headings == [("p1_b0", "affair_text")]
