from openparl_extract.config import load_config


def test_defaults(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_NAME", "LLM_MODEL", "API_BASE", "LLM_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    c = load_config(env_file=None)
    assert c.llm_base_url == "http://localhost:8080/v1"
    assert c.llm_api_key == "none"
    assert c.llm_model == "apertus-8b"
    assert c.api_base == "https://api.openparldata.ch"
    assert c.llm_backend == "apertus"


def test_env_override(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://x/v1")
    monkeypatch.setenv("LLM_MODEL", "apertus-70b")
    c = load_config(env_file=None)
    assert c.llm_base_url == "http://x/v1"
    assert c.llm_model == "apertus-70b"


def test_llm_name_is_the_template_variable_and_wins_over_llm_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_NAME", "apertus-v1.5-8b")
    assert load_config(env_file=None).llm_model == "apertus-v1.5-8b"
    monkeypatch.setenv("LLM_MODEL", "old")  # legacy name only used when LLM_NAME is unset
    assert load_config(env_file=None).llm_model == "apertus-v1.5-8b"
