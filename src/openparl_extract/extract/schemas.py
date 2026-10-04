"""What the LLM returns: smaller than Affair, verified and wrapped into Value[T] later."""
from pydantic import BaseModel, create_model


class ExtractedItem(BaseModel):
    value: str | None = None
    block_id: str | None = None
    quote: str | None = None


class ExtractedQuestion(BaseModel):
    id: str
    text: ExtractedItem


class ExtractedAnswer(BaseModel):
    question_id: str | None = None
    text: ExtractedItem


class ExtractedDecision(BaseModel):
    outcome: ExtractedItem
    date: ExtractedItem
    body: ExtractedItem


class ExtractionResult(BaseModel):
    affair_text: ExtractedItem | None = None
    justification: ExtractedItem | None = None
    questions: list[ExtractedQuestion] = []
    answers: list[ExtractedAnswer] = []
    executive_reasoning: ExtractedItem | None = None
    decision: ExtractedDecision | None = None
    prompt_versions: dict[str, str] = {}
    errors: list[str] = []  # runner problems (client/payload errors), copied into review flags by verify


FIELD_GROUPS = ("affair_text", "justification", "questions", "answers", "executive_reasoning", "decision")


def group_schema(group: str) -> dict:
    """JSON Schema for a model wrapping just one field of ExtractionResult."""
    f = ExtractionResult.model_fields[group]
    return create_model(f"Extract_{group}", **{group: (f.annotation, f.default)}).model_json_schema()
