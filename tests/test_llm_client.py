from openparl_extract.extract.llm_client import LLMClient, MockLLMClient


def test_mock_returns_fixture_copy_and_records():
    fx = {"questions": {"questions": [{"id": "q1"}]}}
    m = MockLLMClient(fx)
    out = m.extract("hi\nFIELD_GROUP: questions\nbody", {}, model="apertus-70b")
    assert out == fx["questions"]
    out["questions"].clear()
    assert fx["questions"]["questions"]
    assert m.calls == [("questions", "apertus-70b")]


def test_mock_unknown_returns_empty():
    m = MockLLMClient({})
    assert m.extract("FIELD_GROUP: decision", {}) == {}
    assert m.extract("nothing", {}) == {}


def test_mock_satisfies_protocol():
    assert isinstance(MockLLMClient({}), LLMClient)
