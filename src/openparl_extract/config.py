import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    api_base: str
    llm_backend: str = "apertus"


def load_config(env_file: str | None = ".env") -> Config:
    if env_file:
        load_dotenv(env_file)  # does not override already-set env vars
    e = os.environ.get
    return Config(
        llm_base_url=e("LLM_BASE_URL", "http://localhost:8080/v1"),
        llm_api_key=e("LLM_API_KEY", "none"),
        llm_model=e("LLM_NAME") or e("LLM_MODEL", "apertus-8b"),  # LLM_NAME: HackApertus template; LLM_MODEL: legacy
        api_base=e("API_BASE", "https://api.openparldata.ch"),
        llm_backend=e("LLM_BACKEND", "apertus"),
    )
