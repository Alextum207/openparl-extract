# openparl-extract

Apertus-driven extraction of Swiss parliamentary affairs (motions, postulates, interpellations, questions, initiatives)
from PDFs into one common schema. **Every extracted value links back to page, block and exact quote**; unclear values
stay `null` with a review flag. Track 2A (OpenParlData) of HackApertus. Project rules and context: [CLAUDE.md](CLAUDE.md),
task split: [TASKS.md](TASKS.md).

## Pipeline

`ingest` (OpenParlData API) -> `parse` (Docling, block IDs) -> `segment` (rules, de/fr/it headings) -> `extract` (Apertus,
per section) -> `verify` (no LLM: quote check, vocabularies, dates, char spans) -> `merge` (API metadata wins, disagreements
logged) -> `evaluate` (gold set, feasibility matrix). Each stage reads and writes JSON under `data/`.

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; use bin/activate elsewhere
pip install -e ".[dev]"
cp .env.example .env                                # Apertus endpoint + key (never commit)
pytest -q
openparl-extract run-all <affair-id> --mock         # plumbing only, no Apertus
openparl-extract pick-corpus && openparl-extract gold-prefill
openparl-extract review                             # gold-review web app (de/it/en)
openparl-extract evaluate                           # metrics + feasibility matrix -> data/reports/
openparl-extract demo                               # median days submission -> answer per parliament
```

Real Apertus runs: see [docs/apertus_integration.md](docs/apertus_integration.md). The mock proves the plumbing only;
no quality claim is made until the pipeline has run on real PDFs and the gold set.

## Docs

- Schema: `src/openparl_extract/models.py`, JSON Schema `schema/affair.v0.1.json` (`openparl-extract export-schema`)
- Mapping to Akoma Ntoso / Popolo / Parla-CLARIN / Docling: [docs/schema_mapping.md](docs/schema_mapping.md)
- API metadata mapping: [docs/metadata_mapping.md](docs/metadata_mapping.md)
- Gold review guides: [DE](docs/gold_review_anleitung.md), [IT](docs/gold_review_guida.md)
- Technical report: [docs/technical_report.md](docs/technical_report.md)

## License

Code: Apache-2.0 (see LICENSE). Data and report: CC-BY-4.0.
