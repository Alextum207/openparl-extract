"""Extract runner: one LLM call per field group (and per chunk), results validated per group, never raises."""
from pydantic import TypeAdapter, ValidationError

from openparl_extract.extract.llm_client import LLMClient
from openparl_extract.extract.prompts import load_prompt
from openparl_extract.extract.schemas import (
    FIELD_GROUPS, ExtractedDecision, ExtractedItem, ExtractionResult, group_schema)
from openparl_extract.parse.blocks import Block
from openparl_extract.segment.rules import SegmentResult, section_blocks

SOURCE = {"affair_text": "affair_text", "justification": "justification", "questions": "questions",
          "answers": "executive_answer", "executive_reasoning": "executive_answer", "decision": "decision"}
ORDER = ("affair_text", "justification", "questions", "answers", "executive_reasoning", "decision")
LISTS = ("questions", "answers")


def _line(b: Block) -> str:
    return f"[{b.id}] {' '.join(b.text.split())}"


def _chunks(blocks: list[Block], max_chars: int) -> list[list[Block]]:
    """Split at block boundaries; an oversized block ends up alone."""
    out: list[list[Block]] = []
    size = 0
    for b in blocks:
        n = len(_line(b)) + 1
        if out and size + n <= max_chars:
            out[-1].append(b)
            size += n
        else:
            out.append([b])
            size = n
    return out


def _first(a, b):
    return a if a is not None else b


def _merge(group: str, parts: list, errors: list[str]):
    if group in LISTS:
        return [x for p in parts for x in p]
    if group == "decision":
        ds = [p for p in parts if p is not None]
        if not ds:
            return None
        first = lambda f: next((getattr(d, f) for d in ds if getattr(d, f).value is not None), getattr(ds[0], f))
        return ExtractedDecision(outcome=first("outcome"), date=first("date"), body=first("body"))
    filled = [p for p in parts if p is not None and p.value is not None]
    if len(filled) > 1:
        errors.append(f"multiple_chunks_single_value:{group}")
    return filled[0] if filled else None


def extract_affair(segments: SegmentResult, blocks: list[Block], client: LLMClient, model: str = "apertus-8b",
                   max_chars: int = 12000, prompt_versions: dict[str, str] | None = None,
                   language: str | None = None) -> ExtractionResult:
    """Configuration errors (missing/pinned-missing prompt template) raise; data and LLM errors are recorded in errors."""
    result = ExtractionResult()
    pinned = prompt_versions or {}
    for group in ORDER:
        src = section_blocks(segments, blocks, SOURCE[group])
        if not src:
            continue
        template, version = load_prompt(group, pinned.get(group))
        result.prompt_versions[group] = version
        questions = "\n".join(f"{q.id}: {q.text.value}" for q in result.questions)
        adapter = TypeAdapter(ExtractionResult.model_fields[group].annotation)
        parts: list = []
        for chunk in _chunks(src, max_chars):
            prompt = (template.replace("{language}", language or "unknown").replace("{questions}", questions)
                      .replace("{blocks}", "\n".join(_line(b) for b in chunk)))
            try:
                payload = client.extract(prompt, group_schema(group), model)
            except Exception as e:
                result.errors.append(f"client_error:{group}:{type(e).__name__}")
                continue
            if not isinstance(payload, dict):
                result.errors.append(f"invalid_payload:{group}:not_a_dict")
                continue
            try:
                parts.append(adapter.validate_python(payload.get(group)) if payload.get(group) is not None
                             else ([] if group in LISTS else None))
            except ValidationError as e:
                msg = str(e.errors()[0]["msg"])[:80] if e.errors() else "invalid"
                result.errors.append(f"invalid_payload:{group}:{msg}")
        if not parts:
            continue
        merged = _merge(group, parts, result.errors)
        if group == "questions":  # ids from the model are replaced: answers refer to the renumbered ids
            for i, q in enumerate(merged, 1):
                q.id = f"q{i}"
        setattr(result, group, merged)
    return result
