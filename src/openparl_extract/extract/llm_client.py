"""LLM interface. Real Apertus client (OpenAI-compatible) is the teammate's job."""
import copy
from typing import Protocol, runtime_checkable

from .schemas import FIELD_GROUPS


@runtime_checkable
class LLMClient(Protocol):
    def extract(self, prompt: str, json_schema: dict, model: str = "apertus-8b") -> dict: ...


class MockLLMClient:
    """Returns fixtures[group] for the group named in a `FIELD_GROUP: <name>` prompt line."""

    def __init__(self, fixtures: dict[str, dict]):
        self.fixtures = fixtures
        self.calls: list[tuple[str, str]] = []

    def extract(self, prompt: str, json_schema: dict, model: str = "apertus-8b") -> dict:
        group = next((g for g in FIELD_GROUPS if f"FIELD_GROUP: {g}" in prompt), None)
        if group is None:
            return {}
        self.calls.append((group, model))
        return copy.deepcopy(self.fixtures.get(group, {}))
