import pytest

from openparl_extract.extract.llm_client import MockLLMClient
from openparl_extract.extract.prompts import load_prompt
from openparl_extract.extract.runner import extract_affair
from openparl_extract.extract.schemas import FIELD_GROUPS
from openparl_extract.parse.blocks import Block
from openparl_extract.segment.rules import SECTIONS, SegmentResult, segment
from openparl_extract.verify.verify import verify


def seg(**secs):
    sections = {s: secs.get(s, []) for s in SECTIONS}
    return SegmentResult(sections=sections, block_section={i: s for s, ids in sections.items() for i in ids})


def blk(i, text, page=1):
    return Block(id=i, page=page, text=text)


def it(v, b, q=None):
    return {"value": v, "block_id": b, "quote": q or v}


class Spy(MockLLMClient):
    def __init__(self, fixtures):
        super().__init__(fixtures)
        self.prompts = []

    def extract(self, prompt, json_schema, model="apertus-8b"):
        self.prompts.append(prompt)
        return super().extract(prompt, json_schema, model)


BLOCKS = [blk("p1_b0", "Motion Velowege"), blk("p1_b1", "Der Regierungsrat soll\nVelowege bauen."),
          blk("p2_b0", "Begruendung: viele Velos."), blk("p2_b1", "Fragen"), blk("p2_b2", "Wie viele Velowege?"),
          blk("p2_b3", "Was kostet es?"), blk("p3_b0", "Antwort des Regierungsrates"),
          blk("p3_b1", "Zu Frage 1: 120 km."), blk("p3_b2", "Beschluss"), blk("p3_b3", "Abgelehnt am 1.2.2024.")]
SEG = seg(affair_text=["p1_b0", "p1_b1"], justification=["p2_b0"], questions=["p2_b1", "p2_b2", "p2_b3"],
          executive_answer=["p3_b0", "p3_b1"], decision=["p3_b2", "p3_b3"])
NONE = it(None, None, None)
FIX = {
    "affair_text": {"affair_text": it("Der Regierungsrat soll", "p1_b1")},
    "justification": {"justification": it("viele Velos.", "p2_b0")},
    "questions": {"questions": [{"id": "x", "text": it("Wie viele Velowege?", "p2_b2")},
                                {"id": "x", "text": it("Was kostet es?", "p2_b3")}]},
    "answers": {"answers": [{"question_id": "q1", "text": it("120 km.", "p3_b1")}]},
    "executive_reasoning": {"executive_reasoning": it("Antwort des Regierungsrates", "p3_b0")},
    "decision": {"decision": {"outcome": it("rejected", "p3_b3", "Abgelehnt"),
                              "date": it("2024-02-01", "p3_b3", "1.2.2024"), "body": NONE}},
}


def test_one_call_per_nonempty_group_in_order():
    c = MockLLMClient(FIX)
    extract_affair(SEG, BLOCKS, c)
    assert [g for g, _ in c.calls] == ["affair_text", "justification", "questions", "answers",
                                      "executive_reasoning", "decision"]


def test_no_call_for_empty_sections():
    c = MockLLMClient(FIX)
    r = extract_affair(seg(affair_text=["p1_b0"]), BLOCKS, c)
    assert [g for g, _ in c.calls] == ["affair_text"]
    assert r.justification is None and r.questions == [] and r.errors == []
    assert r.prompt_versions == {"affair_text": "v1"}


def test_prompt_content_and_question_renumbering():
    c = Spy(FIX)
    r = extract_affair(SEG, BLOCKS, c, language="de")
    p = c.prompts
    assert "[p1_b1] Der Regierungsrat soll Velowege bauen." in p[0]  # newline collapsed
    assert "[p1_b0] Motion Velowege" in p[0] and "FIELD_GROUP: affair_text" in p[0]
    assert "Document language: de" in p[0]
    assert "q1: Wie viele Velowege?" in p[3] and "q2: Was kostet es?" in p[3] and "FIELD_GROUP: answers" in p[3]
    assert [q.id for q in r.questions] == ["q1", "q2"]
    c2 = Spy(FIX)
    extract_affair(seg(affair_text=["p1_b0"]), BLOCKS, c2)
    assert "Document language: unknown" in c2.prompts[0]


def test_chunking_at_block_boundaries_and_merging():
    bl = [blk(f"p1_b{i}", "x" * 40) for i in range(5)] + [blk("p1_b5", "y" * 500)]
    fx = {"questions": {"questions": [{"id": "z", "text": it("x" * 40, "p1_b0")}]},
          "affair_text": {"affair_text": it("y" * 50, "p1_b5")}}
    c = Spy(fx)
    r = extract_affair(seg(questions=[b.id for b in bl[:5]], affair_text=["p1_b5"]), bl, c, max_chars=100)
    q = [p for p in c.prompts if "FIELD_GROUP: questions" in p]
    assert len(q) == 3 and "[p1_b2]" in q[1] and "[p1_b1]" not in q[1]  # 2 + 2 + 1 blocks
    assert [x.id for x in r.questions] == ["q1", "q2", "q3"]  # list groups concatenate, then renumber
    assert r.affair_text.value == "y" * 50 and r.errors == []  # oversized single block: one chunk
    r2 = extract_affair(seg(affair_text=["p1_b0", "p1_b5", "p1_b1"]), bl, MockLLMClient(fx), max_chars=100)
    assert r2.affair_text.value == "y" * 50  # first non-null wins, never concatenated
    assert r2.errors == ["multiple_chunks_single_value:affair_text"]


def test_oversized_block_alone_and_decision_first_non_null_per_field():
    bl = [blk("p1_b0", "a" * 10), blk("p1_b1", "b" * 300), blk("p1_b2", "c" * 10)]
    n = []

    class Seq(MockLLMClient):
        def extract(self, prompt, json_schema, model="apertus-8b"):
            n.append(prompt)
            d = {"outcome": NONE, "date": NONE, "body": NONE}
            if len(n) == 1:
                d["body"] = it("Rat", "p1_b0")
            if len(n) == 2:
                d["body"] = it("OTHER", "p1_b1")
                d["outcome"] = it("adopted", "p1_b1", "a")
            return {"decision": d}

    r = extract_affair(seg(decision=["p1_b0", "p1_b1", "p1_b2"]), bl, Seq({}), max_chars=100)
    assert len(n) == 3 and "[p1_b1]" in n[1] and "[p1_b0]" not in n[1] and "[p1_b2]" not in n[1]
    assert r.decision.body.value == "Rat" and r.decision.outcome.value == "adopted"


def test_invalid_payload_and_client_error_do_not_stop_run():
    class Bad(MockLLMClient):
        def extract(self, prompt, json_schema, model="apertus-8b"):
            if "FIELD_GROUP: justification" in prompt:
                return {"justification": {"value": ["not", "a", "str"]}}
            if "FIELD_GROUP: questions" in prompt:
                raise TimeoutError("slow")
            return super().extract(prompt, json_schema, model)

    r = extract_affair(SEG, BLOCKS, Bad(FIX))
    assert r.justification is None and r.questions == []
    assert r.affair_text is not None and r.decision is not None
    assert any(e.startswith("invalid_payload:justification:") for e in r.errors)
    assert "client_error:questions:TimeoutError" in r.errors


def test_prompt_versions_pinned_and_missing():
    with pytest.raises(FileNotFoundError, match="nope"):
        load_prompt("nope")
    with pytest.raises(FileNotFoundError, match="v99"):
        load_prompt("decision", "v99")
    assert load_prompt("decision")[1] == "v1"
    with pytest.raises(FileNotFoundError):
        extract_affair(SEG, BLOCKS, MockLLMClient(FIX), prompt_versions={"decision": "v99"})
    r = extract_affair(SEG, BLOCKS, MockLLMClient(FIX), prompt_versions={"decision": "v1"})
    assert r.prompt_versions == {g: "v1" for g in FIELD_GROUPS}


@pytest.mark.parametrize("g", FIELD_GROUPS)
def test_shipped_templates(g):
    text, v = load_prompt(g)
    assert v == "v1" and f"FIELD_GROUP: {g}" in text and "{blocks}" in text and "{language}" in text
    assert ("{questions}" in text) == (g == "answers")
    for lang in ("de", "fr", "it"):
        assert f"EXAMPLE ({lang}" in text
    assert "VERBATIM" in text and "null" in text
    if g == "decision":
        for code in ("adopted", "partially_adopted", "rejected", "withdrawn", "written_off",
                     "referred_to_executive", "no_decision", "unknown", "YYYY-MM-DD"):
            assert code in text


def test_end_to_end_with_mock_and_verify():
    blocks = [blk("p1_b0", "Motion"), blk("p1_b1", "Der Regierungsrat soll Velowege bauen."),
              blk("p2_b0", "Antwort des Regierungsrates"), blk("p2_b1", "Zu Frage 1: 120 km."),
              blk("p2_b2", "Beschluss"), blk("p2_b3", "Abgelehnt am 1.2.2024.")]
    s = segment(blocks)
    fx = {"affair_text": {"affair_text": it("Velowege bauen", "p1_b1")},
          "decision": {"decision": {"outcome": it("rejected", "p2_b3", "Abgelehnt"),
                                    "date": it("2024-02-01", "p2_b3", "1.2.2024"), "body": NONE}}}
    v = verify(extract_affair(s, blocks, MockLLMClient(fx)), blocks)
    p = v.affair_text.provenance[0]
    assert v.affair_text.status == "extracted" and blocks[1].text[p.char_start:p.char_end] == "Velowege bauen"
    assert v.decision.outcome.status == "extracted" and str(v.decision.date.value) == "2024-02-01"
    assert v.prompt_versions["decision"] == "v1"
    fx["affair_text"] = {"affair_text": it("Velowege abschaffen", "p1_b1")}
    v2 = verify(extract_affair(s, blocks, MockLLMClient(fx)), blocks)
    assert v2.affair_text.status == "not_found" and "quote_not_found:p1_b1" in v2.review_flags
