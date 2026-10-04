# OpenParlData Track 2A: Implementation Plan (Alexander's part)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (chosen by user) with superpowers:test-driven-development. Steps use checkbox syntax. After approval this file is copied to `docs/superpowers/plans/2026-10-04-openparl-extract.md`.

**Goal:** A Python pipeline (ingest, parse, segment, extract, verify, merge, evaluate) that turns Swiss parliamentary PDFs into the versioned affair schema, with page/block/quote provenance, running fully locally with Apertus.

**Architecture:** Each stage reads and writes JSON files under `data/`, so stages rerun independently. The LLM sits behind one `LLMClient` protocol with a mock and a local OpenAI-compatible implementation (llama.cpp server). Metadata comes from the API; the LLM only extracts what the API lacks; Verify is deterministic and computes character spans.

**Tech Stack:** Python 3.11+ (machine has 3.13), httpx, Docling, Pydantic v2, rapidfuzz, pandas, typer, pytest, llama.cpp `llama-server` (local Apertus GGUF).

**Spec:** `CLAUDE.md` and `TASKS.md` in the repo root (user confirmed these are the approved spec). Deadline 16 Oct 2026, schema freeze 12 Oct.

## Context

The challenge judges (1) insight on whether a common schema is feasible and (2) breadth across parliaments/languages/levels. The user wants the pipeline built now, with the whole thing running locally. Verified facts: OpenParlData API is public, no auth, base `https://api.openparldata.ch`, endpoints `/v1/affairs/` (offset/limit, `body_key`, `expand`, `fields`, `lang`), `/v1/affairs/{id}` (relations: docs, events, votings, persons), `/v1/docs/`, `/v1/docs/{id}`, `/v1/bodies/`; docs at `/documentation`, `/redoc`, spec at `/openapi.json`; bulk NDJSON at `https://files.openparldata.ch/exports/`; license CC BY 4.0 (credit "Source: OpenParlData.ch"). Document field names are NOT yet known: Task 2 reads `openapi.json` first and saves it to `docs/openparldata_openapi.json`.

Local hardware: Windows 11, ~23 GB RAM, AMD Radeon 890M iGPU (no CUDA), Docker present, no Ollama. So Apertus runs on CPU via llama.cpp with a quantized GGUF. Only community GGUFs of Apertus-8B-Instruct-**2509** were found (bartowski, unsloth); a v1.5 GGUF is unconfirmed. 70B does not fit locally.

## Global Constraints

- Extraction model: Apertus only (no other LLM). Local first; no hardcoded URLs or keys, all from `.env`.
- No invented values: absent means `value=None`, `status="not_found"`.
- Every value carries `Provenance(page, block_id, char_start, char_end, quote)`; offsets are computed by Verify, never by the model.
- Do not invent API endpoints: only those listed above, plus whatever `openapi.json` shows.
- Python 3.11+, Pydantic v2, JSON files between stages, prompts as versioned files in `src/openparl_extract/extract/prompts/`.
- Open license (Apache-2.0), public repo, README with samples; raw PDFs gitignored.
- No schema changes after 12 Oct 2026.

## Review Focus

- Scanned PDF with no text layer (Docling OCR returns nothing): expect empty blocks plus a review flag, not a crash.
- Model returns a `block_id` that does not exist or a quote that differs only by whitespace/hyphenation: expect tolerant match when above the threshold, otherwise null plus flag.
- Affair with no linked document in the API: expect `from_metadata` values only and a flag, no extraction call.
- Two questions with the same id or an answer pointing to a missing question: expect a flag and unpaired answer, not silent drop.
- Mixed-language or French/Italian headings with accents and uppercase: segmentation rules must match case-/accent-insensitively.

Each line gets its test in the owning task below.

## File structure

```
pyproject.toml, .env.example, .gitignore, LICENSE (Apache-2.0)
src/openparl_extract/
  models.py            Provenance, Value[T], Affair, vocabularies, export_schema()
  config.py            reads .env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, API_BASE)
  ingest/              api.py (httpx client), store.py (save pdf+json+sha256)
  parse/               docling_parse.py, blocks.py (Block model, header/footer strip)
  segment/             rules.py (heading regexes de/fr/it)
  extract/             llm_client.py (Protocol, MockLLMClient, OpenAICompatClient), schemas.py, runner.py, prompts/*.md
  verify/              verify.py (quote check, spans, vocab, dates)
  merge/               merge.py
  evaluate/            metrics.py, matrix.py, demo.py
  review/              build_review.py (HTML gold-review page)
  cli.py
schema/affair.v0.1.json, docs/schema_mapping.md, data/{raw,parsed,output,gold}/, tests/
```

## Tasks

Every task follows TDD: write failing test, run to see it fail, minimal code, run to pass, commit. Commit message ends with the Co-Authored-By line.

### Task 0: Repo scaffold and local Apertus
- Create: `pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE`, package folders with `__init__.py`; `git init`.
- Local LLM: download a quantized Apertus-8B-Instruct GGUF (Q4_K_M ~5 GB) and `llama-server` (llama.cpp Windows release), start OpenAI-compatible server on localhost. Check first whether a v1.5 GGUF exists; if not use 2509 and document the deviation in the README/report (Hard requirement says v1.5). Write `docs/local_apertus.md` with the exact start command.
- Test: `tests/test_smoke.py` imports the package. Manual check: `curl` to `/v1/chat/completions` returns text; note tokens/s.
- Produces: working venv, `.env` pattern.

### Task 1: models, vocabularies, mock client, interface
- Create: `models.py`, `extract/llm_client.py`, `extract/schemas.py`, `tests/test_models.py`, `tests/test_llm_client.py`.
- Produces: `Provenance`, `Value[T]`, `Affair` (CLAUDE.md section 5), enums for affair_type, actor_role, procedural_state, decision_outcome; `export_schema(path)` writes `schema/affair.v0.1.json`; `LLMClient.extract(prompt: str, json_schema: dict, model: str = "apertus-8b") -> dict`; `MockLLMClient(fixtures: dict)`; extraction output schema `ExtractedItem{value, block_id, quote}` and field-group models (`questions`, `answers`, `decision`, `justification`, ...).
- Tests: `Value` rejects status `extracted` without provenance; unknown vocabulary value fails validation; JSON Schema export is valid; mock returns the fixture for a prompt key.

### Task 2: Ingest
- First step: fetch `https://api.openparldata.ch/openapi.json` to `docs/openparldata_openapi.json` and read the affair and doc field names (PDF URL, text, language, body). Do not guess them.
- Create: `ingest/api.py` (`list_affairs(body_key, limit, offset)`, `get_affair(id)`, `get_doc(id)`), `ingest/store.py` (`save(affair_json, pdf_bytes) -> Path`, SHA256), `tests/test_ingest.py` using `httpx.MockTransport` with recorded sample JSON.
- Review-focus test: affair without docs returns a record with `pdf=None` and is written with flag `no_document`.
- Pagination loop respects `offset` cap 100,000; polite rate limit.

### Task 3: Parse
- Create: `parse/docling_parse.py` (`parse_pdf(path) -> list[Block]`), `parse/blocks.py` (`Block{id: "p{page}_b{idx}", page, bbox, text, type}`, header/footer stripping: lines repeating on >50% of pages or matching page-number patterns).
- Tests use a small PDF generated with reportlab (3 pages with repeated header and page numbers): IDs are stable across two runs; header/footer removed; PDF without text layer returns `[]` and `is_scanned=True` (review-focus test); OCR enabled when `is_scanned`.

### Task 4: Verify
- Create: `verify/verify.py`: `verify(result: ExtractionResult, blocks: list[Block], threshold=90) -> VerifiedAffairParts`.
- Behavior: quote located in the cited block with rapidfuzz `partial_ratio`; `char_start/char_end` computed by exact search, falling back to fuzzy alignment; vocab check; date order submitted <= answered <= decided; at most one answer per question; failures set value to None with `review_flags`.
- Tests (review focus): non-existent block_id; quote differing by hyphenation and whitespace passes; hallucinated quote fails; duplicate question ids and answer to unknown question flagged.

### Task 5: Segment (rules only)
- Create: `segment/rules.py`: `segment(blocks) -> dict[str, list[block_id]]` with headings de/fr/it ("Antwort des Regierungsrates", "Réponse du Conseil d'Etat", "Risposta del Consiglio di Stato", "Begründung", "Exposé des motifs", "Motivazione", ...). Case- and accent-insensitive.
- Tests: three fixture block lists (de/fr/it) map to correct sections; no match returns `other` plus flag `segmentation_failed`.

### Task 6: Extract runner and local client
- Create: `extract/runner.py` (`extract_affair(sections, blocks, client) -> ExtractionResult`, one call per field group), `extract/prompts/{questions,answers,decision,justification}.v1.md` with de/fr/it example each, `OpenAICompatClient` in `llm_client.py` using `response_format` JSON schema (llama.cpp grammar constraint); if rejected: JSON mode + Pydantic validate + one retry with the error text.
- Tests with the mock: runner builds one prompt per section, long sections are split to fit a token budget, prompt file version is recorded in the output; client retry path tested with a fake transport returning invalid JSON then valid JSON.
- Manual check against local llama-server on 3 documents (also supplies the 8B-only numbers for the report; 70B comparison left to the teammate/hosted, noted as not run locally).

### Task 7: Merge
- Create: `merge/merge.py`: API metadata becomes `from_metadata` values (title, type, submitters, dates, status); LLM output cross-checks them; every disagreement appended to `data/output/disagreements.jsonl`.
- Tests: agreeing values stay `from_metadata`; differing date logs a disagreement and keeps the metadata value.

### Task 8: Evaluate and feasibility matrix
- Create: `evaluate/metrics.py` (per field exact/fuzzy match, precision, recall, `not_found` correctness, provenance validity, hallucination rate), `evaluate/matrix.py` (field × level/language: consistent / partial / not representable, thresholds configurable), `tests/test_metrics.py` with hand-computed fixtures.

### Task 9: CLI and end-to-end with mock
- Create: `cli.py` (typer): `ingest`, `parse`, `segment`, `extract`, `verify`, `merge`, `evaluate`, `run-all`. Test: `run-all` on one fixture PDF with the mock produces a valid `Affair` JSON validated against the exported schema.

### Task 10: Corpus, gold prefill, review page
- Create: `scripts/pick_corpus.py` (stratified ~45 candidates by body level × language × scanned × type using API fields; plain-text availability noted), `review/build_review.py` (HTML: PDF page image next to JSON, quotes highlighted, correct/incorrect marking exported to `data/gold/*.json`).
- Test: build_review produces HTML containing every quote of a fixture affair.

### Task 11: Demo query, docs
- Create: `evaluate/demo.py` (median days submission to executive answer for interpellations per canton, from metadata/events), `README.md`, `docs/schema_mapping.md`, `docs/technical_report.md` skeleton from the HackApertus template.

## Timeline

| Date | Tasks |
|------|-------|
| 4-5 Oct | 0, 1, 2 |
| 5-7 Oct | 3, 4, 5, 9 (mock end-to-end) |
| 7-9 Oct | 6, 7, local Apertus runs; corpus (10); 8 Oct Q&A session with OpenParlData |
| 9-12 Oct | 8, gold prefill, review page, schema freeze 12 Oct |
| 10-14 Oct | gold review (~30 docs, ~1 h/day), evaluation runs |
| 14-16 Oct | 11, README, report, buffer |

## Verification

- `pytest -q` green after every task; `ruff` clean.
- `openparl-extract run-all tests/fixtures/sample.pdf --mock` yields schema-valid JSON.
- With local llama-server: `run-all` on 3 real PDFs from the API; check every value has provenance and `verify` flags non-matching quotes; record tokens/s and time per document.
- `evaluate` on the gold set prints per-field metrics and writes the feasibility matrix CSV.

## Risks and open points

- Local CPU inference is slow (8B Q4, likely a few tokens/s): plan ~30 s to several minutes per document; run extraction in the background overnight, use block-level section splitting to keep prompts short.
- No v1.5 GGUF confirmed: fallback to 2509 must be stated openly; conversion of v1.5 weights with llama.cpp `convert_hf_to_gguf.py` is a possible follow-up.
- 70B cannot run locally; comparison only if the teammate gets hosted access.
- The public repo `hatif03/openparldata-extract` (same challenge) exists; we do not copy from it.
- The teammate's scope shrinks to prompt quality, hosted 70B comparison, and report text; the local client and server setup are covered in Tasks 0 and 6.
