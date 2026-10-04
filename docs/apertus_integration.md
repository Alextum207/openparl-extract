# Apertus integration (hand-off)

The pipeline is complete except the real LLM client. It runs today with `--mock`; this page is the contract for the Apertus side.

## Contract

File `src/openparl_extract/extract/apertus_client.py`, class `ApertusClient`:

```python
class ApertusClient:
    def __init__(self, base_url: str, api_key: str, model: str): ...
    def extract(self, prompt: str, json_schema: dict, model: str | None = None) -> dict: ...
```

`extract` returns the parsed JSON object matching `json_schema` (`model` overrides the default, e.g. `apertus-70b` for hard groups).
`extract/llm_client.py:load_client` imports it when `--mock` / `LLM_BACKEND=mock` is not set, using `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` from `.env`. Without the module it raises a clear RuntimeError.

## Requirements

- OpenAI-compatible endpoint (vLLM, llama-server, Infomaniak). Nothing hardcoded; config comes from `.env`.
- Structured output: use guided decoding / `response_format` with `json_schema` where the server supports it. Fallback: JSON mode, validate against `json_schema`, one retry that includes the validation error text, then raise.
- Timeouts, bounded retries with backoff on 429/5xx, respect rate limits.
- Raise on transport errors. The runner catches them and records `client_error:<group>:<Type>`; never swallow them and return `{}`.
- Never fabricate block ids or quotes. If the model returns nothing useful return the group with null/empty values; `verify` drops anything it cannot find in the cited block (quote check), so the client must pass values through unchanged and not "repair" them.

## How prompts reach the client

One call per field group (and per chunk of at most `--max-chars`). The prompt text contains the line `FIELD_GROUP: <group>` (affair_text, justification, questions, answers, executive_reasoning, decision). The expected schema is `extract/schemas.py:group_schema(group)`, e.g. `{"questions": [{"id", "text": {"value", "block_id", "quote"}}]}`. Blocks are listed as `[p2_b3] text`.

## Testing against the pipeline

```
openparl-extract ingest --body-key GL --limit 3
openparl-extract parse --body-key GL
openparl-extract segment --body-key GL
openparl-extract extract --body-key GL --limit 3   # real client; add --force to rerun
openparl-extract verify --body-key GL && openparl-extract merge --body-key GL
```

Inspect `data/extracted/<body_key>/<id>/extraction.json` (raw model output) and `data/verified/.../verified.json` (what survived the quote check; `review_flags` show why not). `openparl-extract evaluate` reports provenance validity and hallucination rate.

## Prompts

`extract/prompts/<group>.v1.md`, versioned (add `.v2.md`, never edit a released version in place; pin with `prompt_versions`). The v1 prompts are first drafts for you to refine:

- Use real umlauts (ä, ö, ü, ß) in the examples; they currently avoid them.
- Handle answers without question numbering (a single prose answer): `question_id` must be null, not guessed.
- Add fr/it examples and check the "quote must be copied verbatim, one block, no ellipsis" instruction holds for 8B.
- Test long answers that span chunks (merging is done by the runner).
