# CLAUDE.md: OpenParlData Track 2A (HackApertus)

Project briefing for Claude Code. Read this file fully before writing any code.
Section 1 is our summary, Sections 2 to 9 are our approach and rules, Section 10 is the original challenge text (authoritative).

---

## 1. What we are building (one sentence)

A versioned schema for Swiss parliamentary affairs plus a Python pipeline that uses **Apertus** to extract that schema from real parliamentary PDFs, where **every extracted value links back to its page and text span**, and an evaluation that shows where a common schema works across parliaments and where it breaks.

**Judging:** (1) Insight: is a common schema feasible, which parts are consistent, where do differences remain? A well-founded negative or partial answer counts as success. (2) Breadth: works across parliaments, document types, languages, government levels.

---

## 2. Hard requirements (never violate)

1. **Model:** Apertus v1.5 (8B or 70B). No other LLM for extraction.
2. **No invented values.** If a value is not clearly in the source, it is `null` with status `not_found`. Never guess.
3. **Provenance for every extracted value:** page number, block ID, and where possible character span plus the exact quoted source text.
4. **Distinguish extracted vs. inferred vs. metadata.** Every value carries a status (see schema).
5. **Faithful wording.** Do not paraphrase or alter the meaning of questions, answers or decisions. Formatting cleanup is allowed (remove headers, footers, page numbers, hyphenation).
6. **Flag, don't guess.** Unreliable cases go to a review flag, not into the data silently.
7. **Open and reusable.** Public repo, open license, README with context and samples.
8. **Production fit:** Python, Pydantic models, output that could later run in a container next to OpenParlData's FastAPI/PostgreSQL stack.
9. **Do not invent API endpoints or URLs.** The original text below lost its links. Look up the OpenParlData API docs at openparldata.ch, or ask.

---

## 3. Pipeline architecture

```
OpenParlData API ──► 1. Ingest ──► 2. Parse ──► 3. Segment ──► 4. Extract ──► 5. Verify ──► 6. Merge ──► JSON (schema)
                     (metadata,     (Docling,     (sections:     (Apertus,      (no LLM:      (with API        │
                      PDFs)          OCR, block    question,      constrained    quote check,  metadata)        ▼
                                     IDs)          answer, ...)   JSON + refs)   vocab, dates)            7. Evaluate
                                                                                                          (gold set)
```

1. **Ingest** (`ingest/`): fetch affair metadata and linked PDFs from the OpenParlData API. Store PDF + metadata + SHA256 locally. Reuse existing plain text (PDFBox/Tika) where available as a fallback/cross-check.
2. **Parse** (`parse/`): Docling for layout, OCR enabled for scanned PDFs. Output a list of text blocks, each with a stable ID (`p{page}_b{index}`), page, bbox, text, block type (heading, paragraph, table, image, signature/stamp). Strip running headers/footers.
3. **Segment** (`segment/`): assign blocks to affair sections: `affair_text`, `justification`, `questions`, `executive_answer`, `decision`, `annex`, `other`. **Rules only in v1** (headings like "Antwort des Regierungsrates", "Réponse du Conseil d'Etat", "Risposta del Consiglio di Stato"). Documents no rule matches get a review flag and are counted in the evaluation. An Apertus fallback is a later option, not part of v1.
4. **Extract** (`extract/`): Apertus fills the schema **per section / per field group**, not one giant prompt. Scope: only what API metadata does not provide (questions, answers and their pairing, executive reasoning, justification, decision) plus a few cross-check fields. Output is constrained to the extraction output schema (see Section 4). The model must return block IDs and the exact quote for each value, **never character offsets**. 70B for hard parts (question–answer pairing, decisions) if the comparison shows it is worth it. If guided decoding is unavailable: JSON mode, Pydantic validation, one retry with the error message.
5. **Verify** (`verify/`): deterministic, no LLM. Checks: quote exists in the referenced block (fuzzy match with rapidfuzz, threshold configurable), values in controlled vocabularies, date plausibility (submitted ≤ answered ≤ decided), every question has at most one answer. **Computes `char_start`/`char_end`** by locating the quote in the block. Failing values: set to `null`, add a `review_flags` entry.
6. **Merge** (`merge/`): title, type, submitters, dates, status already exist as structured API metadata. Use them as `from_metadata`, do not re-extract; use the LLM output only as a cross-check and log disagreements.
7. **Evaluate** (`evaluate/`): compare against the gold set (Section 6).

---

## 4. Work split and interface

- **Alexander (with Claude Code):** main pipeline (ingest, parse, segment, verify, merge, evaluate), schema, CLI, gold-review tool, README.
- **Teammate:** Apertus integration (hosting/provider, prompts, structured output via e.g. vLLM guided decoding or Outlines), 8B vs 70B comparison.
- **Together:** schema v0.1 and the extraction output schema, gold set review, demo question, report, pitch.
- Full task list and dates: `TASKS.md`. Deadline 16 Oct 2026, schema freeze 12 Oct, real endpoint expected 7 Oct.

**Interface contract** (build this first so both sides can work in parallel):

```python
# extract/llm_client.py
class LLMClient(Protocol):
    def extract(self, prompt: str, json_schema: dict, model: str = "apertus-8b") -> dict: ...
```

- Assume an OpenAI-compatible endpoint (base URL + key from `.env`, never hardcoded).
- Provide a `MockLLMClient` that returns fixture JSON, so the pipeline runs and is testable without Apertus.
- **Extraction output schema** (`extract/schemas.py`): what the model returns is a smaller shape than the final `Affair`: per field group, items of `{value, block_id, quote}` and `null` when absent. It has no status, no page and no offsets. Verify and Merge turn it into `Value`/`Provenance` objects. Pass its JSON Schema as `json_schema`.

---

## 5. Schema draft (v0.1, to be refined)

Every leaf value is wrapped:

```python
class Provenance(BaseModel):
    page: int
    block_id: str
    char_start: int | None
    char_end: int | None
    quote: str            # exact source text

class Value(BaseModel, Generic[T]):
    value: T | None
    status: Literal["extracted", "from_metadata", "inferred", "not_found"]
    provenance: list[Provenance] = []
    review_flag: str | None = None
```

Top-level `Affair`:

- `schema_version`
- `source`: openparldata_id, parliament, level (`federal` | `cantonal` | `municipal`), language (`de` | `fr` | `it` | `rm`), document_url, pdf_sha256, is_scanned
- `affair_type`: controlled vocab (below), plus `original_type_label` (verbatim, e.g. "Kleine Anfrage")
- `reference_number`, `title`
- `actors`: list of {name, role, party, faction}
- `addressed_body` (e.g. Regierungsrat, Gemeinderat, Bundesrat)
- `affair_text`, `justification`
- `questions`: list of {id, text}
- `answers`: list of {question_id or null, text}, plus general `executive_reasoning`
- `decision`: {outcome, date, body}
- `procedural_history`: list of {date, event, state}
- `related_affairs`: list of references
- `annexes`, `tables`, `images`: kept as references with page and caption, not interpreted
- `review_flags`: list of strings

**Controlled vocabularies (draft):**

- affair_type: `motion`, `postulate`, `interpellation`, `written_question`, `parliamentary_initiative`, `cantonal_initiative`, `popular_initiative`, `resolution`, `other`
- actor_role: `submitter`, `co_signatory`, `spokesperson`, `executive_respondent`, `committee`
- procedural_state: `submitted`, `answered`, `debated`, `referred`, `decided`, `written_off`, `withdrawn`, `pending`
- decision_outcome: `adopted`, `partially_adopted`, `rejected`, `withdrawn`, `written_off`, `referred_to_executive`, `no_decision`, `unknown`

Keep a mapping table in `docs/schema_mapping.md` from our concepts to Akoma Ntoso, Popolo, Parla-CLARIN and Docling. Ship a JSON Schema export (`schema/affair.v0.1.json`) generated from the Pydantic models.

---

## 6. Evaluation plan

- **Gold set:** 30 to 50 documents, manually checked, stratified across level (federal/cantonal/municipal) × language (de/fr/it) × born-digital/scanned × affair type. Store as JSON in `data/gold/`. Pick ~60 candidates, pre-fill gold files with pipeline output, and review them in a simple HTML tool (PDF page next to JSON, quotes highlighted). Humans correct, they do not write from scratch. Review window 10 to 14 Oct; the final size depends on available review time, state the real size in the report.
- **Metrics per field:** exact/fuzzy match, precision, recall, `not_found` correctness.
- **Provenance validity:** share of values whose quote is found in the cited block.
- **Hallucination rate:** share of extracted values not supported by the source (the key number for "can it run unattended?").
- **Feasibility matrix (the insight deliverable):** per schema field × parliament/level/language: consistent / partially / not representable. This answers the main judging question.
- **Demo:** answer at least one cross-parliamentary question that is not reliably answerable today (example: median time between submission and executive answer for interpellations, compared across cantons; or share of motions adopted per level).

---

## 7. Repo structure

```
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── src/openparl_extract/
│   ├── models.py          # Pydantic schema + vocabularies
│   ├── ingest/
│   ├── parse/
│   ├── segment/
│   ├── extract/           # llm_client.py, prompts/
│   ├── verify/
│   ├── merge/
│   ├── evaluate/
│   └── cli.py
├── schema/                # exported JSON Schema, versioned
├── docs/                  # schema docs, mapping table, technical report
├── data/                  # raw/, parsed/, output/, gold/  (raw PDFs gitignored)
└── tests/
```

Use the official template as the base: https://github.com/HackApertus/project-template (technical report: `track_2a/technical_report.md`).

---

## 8. Tech stack

Python 3.11+, httpx (API), Docling (parsing + OCR), Pydantic v2 (schema + validation), rapidfuzz (quote check), pandas (evaluation), typer (CLI), pytest. Apertus via OpenAI-compatible client (teammate decides provider: self-hosted vLLM or Infomaniak).

---

## 9. Working rules for Claude Code

- Build in this order: models.py + MockLLMClient → ingest → parse → verify → segment → extract → merge → evaluate. The pipeline must run end-to-end with the mock early.
- Small, testable modules; each stage reads and writes JSON files so stages can be rerun independently.
- Prompts live in `extract/prompts/` as files, versioned, multilingual examples (de/fr/it).
- Never write a value without provenance. Never drop a `review_flag` silently.
- Log every disagreement between API metadata and extracted values.
- When unsure about the API, document structure or a schema decision: ask instead of guessing.
- Dates: deadline 16 Oct 2026, schema freeze 12 Oct. After the freeze no schema changes, only prompt and code fixes.
- Do not claim a stage works on real data until it ran on real PDFs; the mock only proves the plumbing.

---

## 10. Original challenge text (authoritative)

> Note: links in the original were lost when copying. Find them on openparldata.ch and the HackApertus GitHub.

Track 2A: OpenParlData
Extracting Parliamentary Affairs from PDFs into One Common Structure

🎯 Challenge Overview
Domains: Public Sector / GovTech / Democracy / Politics

→ Context & Background
Switzerland has parliaments at three levels — the Federal Assembly, 26 cantonal parliaments, and several hundred municipal/city parliaments — operating across different languages. Most proceedings involve a common object: a parliamentary affair (motion, postulate, interpellation, written question or initiative), submitted by members, answered by the executive, and usually closed by a decision. OpenParlData (openparldata.ch) scrapes 90 Swiss parliaments daily and publishes ~300,000 parliamentary affairs as open data, via API () and bulk exports ().
Much valuable information is buried in parliamentary PDFs and can't be reliably extracted into structured form — the question asked, the government's answer and reasoning, the decision, the people involved. Documents vary hugely: born-digital, scanned, some with handwritten stamps/signatures, tables and annexes. Generic document AI (e.g. Docling) gives a clean but domain-agnostic page representation; ad-hoc LLM prompting produces a different JSON shape for every body. OpenParlData already runs the surrounding infrastructure (a prompt-driven extraction workbench with side-by-side PDF / Text / JSON / Docling views and a manual review step), so what this challenge produces can go into real operation, not just a demo.

→ Problem Description
There is no shared, machine-readable format in which a parliamentary affair can be expressed so two parliaments become comparable — and no reliable way to produce one from existing PDFs. Three gaps:
Format gap. Docling/plain text are too generic (document structure, not affair semantics); Akoma Ntoso is rich but heavyweight and rooted in legislative drafting; TEI/Parla-CLARIN targets speech/debate transcripts. What's missing is a middle layer (like JATS for scientific papers) that preserves document structure and captures affair semantics (type, submitter & co-signatories, addressed body, question/answer pairings, dates, procedural history, decisions, links to related affairs).
Extraction gap. Turning heterogeneous, multilingual, partly-scanned PDFs into that format at 300,000-document scale needs an LLM — and an unconstrained, untraceable LLM invents values.
Verification gap. No gold standard and no metric, so nobody can say whether a pipeline is good enough to run unattended.

→ Primary Objective
Design and prototype a structured representation model for parliamentary affairs, plus a working Apertus-driven pipeline that produces it from real PDFs. Three deliverables:
The representation model — a versioned, documented schema + controlled vocabularies (affair types, actor roles, procedural states, decision outcomes). Small enough for a municipality, expressive enough for national parliaments; handles embedded images, tables (e.g. budgets), annexes. Ideally maps concepts to existing standards (Akoma Ntoso, Parla-CLARIN, Popolo, Docling).
The converter — prompts + code turning real PDFs into valid structured data using Apertus, with provenance: each value keeps a reference to page and, where possible, the text span, so a reviewer can verify quickly.
The evidence — evaluate on a multilingual, multi-level sample against a manually-checked gold set, and demonstrate value by answering at least one cross-parliamentary question that can't currently be answered reliably.

🔧 Resources, Tools & Support
→ Datasets
Provided by OpenParlData:
Full corpus — ~300,000 parliamentary affairs (federal/cantonal/municipal) with structured metadata (title, type, contributors, dates, status, events) + linked source documents. Public REST API:  (docs at ).
Source documents — original PDFs (born-digital and scanned), plus already-extracted plain text (Apache PDFBox/Tika) for a large subset.
Data protection — the corpus contains only material already published by the parliaments themselves.
→ Supporting Materials
PDFs as binary files:
→ Mentorship
Technical/domain questions handled in the online Q&A sessions with the challenge provider (dates below). Check out our mentors: link

💻 Technical Preferences
Preferred languages / frameworks
No restriction. For reference, the production stack is Python (FastAPI, Pydantic) with PostgreSQL and an Angular/React front end; ETL pipelines use Apache Hop.
Recommended platforms
Develop locally to start. OpenParlData runs on a self-managed VPS with a GitLab deploy process; ~20 GB RAM available for self-hosted LLMs on prod, though a specific LLM provider (e.g. Infomaniak) is intended. A dedicated container can later be added to OpenParlData's docker-compose landscape.
Specific AI models
Apertus v1.5 — 8B or 70B
Model sources
huggingface.co/swiss-ai/Apertus-v1.5-8B
huggingface.co/swiss-ai/Apertus-v1.5-70B

📦 Deliverables & Judging
Github repo template:
https://github.com/HackApertus/project-template
→ Expected outputs
A reference implementation: a public repository containing the PDF-to-schema converter, the Apertus prompts, possibly a validator, and a README with context and samples.
Technical report template (can be adjusted):
https://github.com/HackApertus/project-template/blob/main/track_2a/technical_report.md
→ Success criteria
The main criterion is insight: does the team reach a well-founded conclusion on whether a common schema for parliamentary affairs is feasible, which parts can be represented consistently across parliaments, and where fundamental differences remain? A convincing negative or partial answer counts as success. If a workable schema emerges, demonstrate it on a broad, diverse set of real documents — showing an LLM can reliably transform heterogeneous PDFs into the schema across document types, languages and levels of government.
→ Evaluation criteria
Insight — how well the submission answers whether a common schema is feasible.
Breadth & applicability — how well the approach works across different parliaments, document types and languages.

⚖️ Ethics & Compliance
→ Ethical guidelines
Minimise hallucinations and keep extracted content traceable to the original source. Favour conservative extraction — do not introduce, omit or substantively alter information present in the source; stay faithful to the original wording and meaning (the original PDF always remains the authoritative reference). Significant formatting changes are encouraged where they improve usability (removing page numbers/headers/footers, restructuring, improving readability, preserving/adding links). Clearly distinguish extracted content from generated/inferred content; where information can't be reliably extracted, make that transparent rather than guess.
→ Legal & compliance
All outputs should be openly accessible and reusable. Parliamentary affairs and related documents are assumed to be generally publicly accessible, and not necessarily protected by copyright.

📅 Online Session
📆 02 October, 14:30-15:15 CET
📆 08 October, 12:00-12:30 CET
Speaker: Christian Gutknecht, OpenParlData / Glue AG

FAQ
What am I building, in one sentence?
A structured representation (schema) for parliamentary affairs plus an Apertus-driven pipeline that extracts it from real parliamentary PDFs, with provenance back to the source.
What data do I get?
~300,000 affairs with metadata via the OpenParlData API, plus original PDFs (born-digital and scanned) and pre-extracted plain text for a large subset.
Which model should I use?
Apertus. Language/framework are otherwise unrestricted.
Is a "negative" result acceptable?
Yes — the main criterion is insight. A well-founded conclusion that a common schema is only partly feasible (and where it breaks) counts as success.
What matters most in the extraction?
Traceability and faithfulness — conservative extraction, no invented values, each value linked to its page/text span; unreliable cases flagged rather than guessed.
Can this go into production?
Potentially yes — OpenParlData already runs the surrounding extraction workbench and import workflow, so a good result can be put into real operation.
