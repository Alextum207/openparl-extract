import json
from datetime import date

import pytest
from pydantic import ValidationError

from openparl_extract.extract.schemas import FIELD_GROUPS, ExtractionResult, group_schema
from openparl_extract.models import (
    Affair, AffairType, Provenance, Source, Value, export_schema,
)

PROV = Provenance(page=1, block_id="p1_b0", quote="Frage")


def test_extracted_requires_provenance():
    with pytest.raises(ValidationError):
        Value[str](value="x", status="extracted")


def test_extracted_requires_value():
    with pytest.raises(ValidationError):
        Value[str](value=None, status="extracted", provenance=[PROV])


def test_not_found_requires_none():
    with pytest.raises(ValidationError):
        Value[str](value="x", status="not_found")
    assert Value[str](value=None, status="not_found").value is None


def test_from_metadata_no_provenance():
    assert Value[str](value="T", status="from_metadata").provenance == []


def test_unknown_vocab_fails():
    with pytest.raises(ValidationError):
        Value[AffairType](value="petition", status="from_metadata")


def _affair():
    return Affair(
        source=Source(openparldata_id="1", parliament="BE", level="cantonal", language="de",
                      document_url="https://example.org/a.pdf", pdf_sha256="0" * 64, is_scanned=False),
        affair_type=Value[AffairType](value="motion", status="from_metadata"),
        original_type_label=Value[str](value="Motion", status="from_metadata"),
    )


def test_affair_roundtrip():
    a = _affair()
    assert Affair.model_validate_json(a.model_dump_json()) == a
    assert a.schema_version == "0.1"


def test_date_value():
    v = Value[date](value="2024-01-02", status="from_metadata")
    assert v.value == date(2024, 1, 2)


def test_export_schema(tmp_path):
    p = tmp_path / "s.json"
    export_schema(p)
    assert json.loads(p.read_text(encoding="utf-8"))["title"] == "Affair"


def test_extraction_result_multilingual():
    r = ExtractionResult.model_validate({
        "questions": [
            {"id": "q1", "text": {"value": "Wie viele?", "block_id": "p1_b2", "quote": "Wie viele?"}},
            {"id": "q2", "text": {"value": "Combien ?", "block_id": "p1_b3", "quote": "Combien ?"}},
            {"id": "q3", "text": {"value": "Quanti?", "block_id": "p1_b4", "quote": "Quanti?"}},
        ],
        "answers": [{"question_id": "q1", "text": {"value": "Zehn.", "block_id": "p2_b0", "quote": "Zehn."}}],
    })
    assert len(r.questions) == 3 and r.decision is None


def test_group_schema_only_requested():
    assert set(FIELD_GROUPS) == {"affair_text", "justification", "questions", "answers",
                                 "executive_reasoning", "decision"}
    s = group_schema("questions")
    assert list(s["properties"]) == ["questions"]
