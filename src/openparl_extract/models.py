"""Affair schema v0.1: every leaf value is a Value[T] with status and provenance."""
from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, model_validator

T = TypeVar("T")


class AffairType(StrEnum):
    motion = "motion"
    postulate = "postulate"
    interpellation = "interpellation"
    written_question = "written_question"
    parliamentary_initiative = "parliamentary_initiative"
    cantonal_initiative = "cantonal_initiative"
    popular_initiative = "popular_initiative"
    resolution = "resolution"
    other = "other"


class ActorRole(StrEnum):
    submitter = "submitter"
    co_signatory = "co_signatory"
    spokesperson = "spokesperson"
    executive_respondent = "executive_respondent"
    committee = "committee"


class ProceduralState(StrEnum):
    submitted = "submitted"
    answered = "answered"
    debated = "debated"
    referred = "referred"
    decided = "decided"
    written_off = "written_off"
    withdrawn = "withdrawn"
    pending = "pending"


class DecisionOutcome(StrEnum):
    adopted = "adopted"
    partially_adopted = "partially_adopted"
    rejected = "rejected"
    withdrawn = "withdrawn"
    written_off = "written_off"
    referred_to_executive = "referred_to_executive"
    no_decision = "no_decision"
    unknown = "unknown"


class Level(StrEnum):
    federal = "federal"
    cantonal = "cantonal"
    municipal = "municipal"


class Language(StrEnum):
    de = "de"
    fr = "fr"
    it = "it"
    rm = "rm"


class Provenance(BaseModel):
    page: int
    block_id: str
    char_start: int | None = None
    char_end: int | None = None
    quote: str


class Value(BaseModel, Generic[T]):
    value: T | None = None
    status: Literal["extracted", "from_metadata", "inferred", "not_found"]
    provenance: list[Provenance] = []
    review_flag: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.status == "extracted" and (self.value is None or not self.provenance):
            raise ValueError("status 'extracted' requires a value and provenance")
        if self.status == "not_found" and self.value is not None:
            raise ValueError("status 'not_found' requires value None")
        return self


class Source(BaseModel):
    openparldata_id: str
    parliament: str  # localized body name (display only)
    body_key: str | None = None  # stable body identifier; use this for grouping
    level: Level
    language: Language
    document_url: str | None = None
    pdf_sha256: str | None = None
    is_scanned: bool | None = None


class Actor(BaseModel):
    name: Value[str]
    role: Value[ActorRole]
    party: Value[str] | None = None
    faction: Value[str] | None = None


class Question(BaseModel):
    id: str
    text: Value[str]


class Answer(BaseModel):
    question_id: str | None = None
    text: Value[str]


class Decision(BaseModel):
    outcome: Value[DecisionOutcome]
    date: Value[date]
    body: Value[str]


class ProceduralEvent(BaseModel):
    date: Value[date]
    event: Value[str]
    state: Value[ProceduralState]


class RelatedAffair(BaseModel):
    reference: Value[str]
    openparldata_id: str | None = None


class Reference(BaseModel):
    """Annex, table or image kept as a pointer, not interpreted."""
    page: int
    caption: str | None = None
    block_id: str | None = None


class Affair(BaseModel):
    schema_version: str = "0.1"
    source: Source
    affair_type: Value[AffairType]
    original_type_label: Value[str]
    reference_number: Value[str] | None = None
    title: Value[str] | None = None
    actors: list[Actor] = []
    addressed_body: Value[str] | None = None
    affair_text: Value[str] | None = None
    justification: Value[str] | None = None
    questions: list[Question] = []
    answers: list[Answer] = []
    executive_reasoning: Value[str] | None = None
    decision: Decision | None = None
    procedural_history: list[ProceduralEvent] = []
    related_affairs: list[RelatedAffair] = []
    annexes: list[Reference] = []
    tables: list[Reference] = []
    images: list[Reference] = []
    review_flags: list[str] = []


def export_schema(path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(Affair.model_json_schema(), indent=2, ensure_ascii=False), encoding="utf-8")
