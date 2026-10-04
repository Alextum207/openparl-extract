Task Split: OpenParlData Track 2A

Goal: a common schema for Swiss parliamentary affairs plus a Python pipeline that uses Apertus to extract it from real PDFs. Every extracted value must point back to its page and the exact source text. No invented values: if something is not clearly in the document, it stays empty and gets flagged.

Deadline: 16 October 2026. Schema freeze: 12 October. Alexander builds with Claude Code (full days); the Teammate's part is the Apertus side. Gold-set review time of both people is the scarcest resource.

## Milestones

| Date | Milestone | Owner |
|------|-----------|-------|
| 4 Oct | Interface contract + extraction output schema agreed (see "Together", first block) | both |
| 4-7 Oct | Full pipeline Ingest to Evaluate runs end-to-end with the mock | Alexander |
| 7 Oct | Real Apertus endpoint reachable (OpenAI-compatible), URL + key in `.env` | Teammate |
| 8 Oct | Ask OpenParlData questions in the online session (12:00-12:30): API docs, which affairs have PDFs, plain-text availability | both |
| 7-10 Oct | Corpus of ~60 documents picked; prompts iterated on de/fr/it; 8B vs 70B check on ~5 documents | Teammate (prompts), Alexander (corpus) |
| 10-14 Oct | Gold review (30-50 documents), evaluation, feasibility matrix, demo question | both |
| 12 Oct | Schema freeze (v0.1 final, no more changes) | both |
| 14-16 Oct | README, technical report, pitch, buffer | both |

## Alexander (with Claude Code): main pipeline

- Set up the GitHub repo from the HackApertus project template (https://github.com/HackApertus/project-template), Python 3.11+, one folder per pipeline stage, `.env` for keys, open license.
- Schema as Pydantic models (affair type, title, reference number, actors, addressed body, questions, answers, decision, procedural history, related affairs, annexes and tables). Every value carries its status (extracted, from metadata, inferred, not found) and its source (page, block ID, exact quote, character span). Export a JSON Schema and keep the mapping table to Akoma Ntoso / Popolo / Parla-CLARIN / Docling.
- Controlled vocabularies: affair types, actor roles, procedural states, decision outcomes.
- Ingest: fetch affairs, metadata and PDFs from the OpenParlData API (look up the real endpoints in the API docs, do not guess them), store with SHA256. Keep the existing plain text as a cross-check.
- Parse with Docling (OCR for scans). Stable block IDs like p3_b12, position, block type. Remove headers, footers, page numbers.
- Segment: rule-based only (headings in de/fr/it). No Apertus fallback in v1. Documents that no rule matches get a review flag and are counted in the evaluation.
- Verify (no LLM): the quote exists in the cited block, values are in the vocabularies, dates make sense, each question has at most one answer. Character spans are computed here by searching the quote in the block, the model is never asked for offsets. Failing values become empty plus a review flag.
- Merge: title, type, submitters, dates and status come from the API metadata. The model output is only a cross-check, every disagreement is logged.
- Evaluate: per field and per parliament, precision, recall, `not_found` correctness, provenance validity, hallucination rate.
- Feasibility matrix: per schema field and parliament/level/language: consistent, partly, not representable. This is the main answer for the judges.
- `MockLLMClient` returning fixed example JSON, so everything runs without Apertus.
- Review tool for the gold set: a simple HTML page with PDF page next to the pre-filled JSON and the quotes highlighted, so checking is fast.
- Pre-fill the gold files with pipeline output so the Teammate and Alexander only correct, not write from scratch.
- README and the technical report skeleton.

## Teammate: Apertus integration

- Get Apertus v1.5 running and share the endpoint by 7 Oct. Hosted (e.g. Infomaniak) is fine and faster than self-hosting; it must still be Apertus. OpenAI-compatible API. Note: OpenParlData's production machine has ~20 GB RAM, so only the 8B can run there.
- One Python class implementing `LLMClient.extract(prompt, json_schema, model) -> dict` (the contract is in CLAUDE.md, section 4). URL and key from `.env`.
- Structured output that matches the schema (vLLM guided decoding or Outlines). If the provider does not support it: JSON mode, validate with Pydantic, retry once with the validation error in the prompt.
- Extraction prompts, as separate versioned files in `extract/prompts/`. Scope: only what the API metadata does not give us: questions, answers (with question pairing), executive reasoning, justification, decision, plus a few cross-check fields. The model gets the blocks of one section with their IDs and returns each value with block ID and exact quote. It returns null if the text does not contain it. It does not return character offsets.
- Prompts in German, French and Italian, one short example per language.
- Technical details: timeouts, retries, rate limits, documents too long for one prompt (split by section).
- 8B vs 70B on about 5 documents early (quality, speed, cost), then again on the gold set. Decision which model does which step.
- Prompt section of the technical report: which prompt version produced which results.

## Together

- First day: agree on schema v0.1 and on the extraction output schema, i.e. the small JSON shape the model returns per field group (value, block_id, quote). This is not the same as the final Affair schema. Both build against it. Changes only after a short check with each other, none after 12 Oct.
- Gold set: 30 to 50 documents checked by hand, spread across federal, cantonal and municipal level, German, French and Italian, born-digital and scanned, different affair types. Split the review by language (e.g. Alexander de, Teammate fr/it), 10-14 Oct, with the review tool above.
- Pick one cross-parliament question for the demo (e.g. median days from submission to executive answer for interpellations, per canton) and answer it with our data.
- Final pitch: what works, where the common schema breaks, and why. A clear partial or negative answer counts as success.
