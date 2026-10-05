# Technical report: openparl-extract

- **Track:** Track 2A: OpenParlData
- **Event:** Online
- **Team:** TODO team name: Alexander Saade, TODO teammate
- **Demo:** TODO link

## 1. Summary
TODO after evaluation: problem, approach, headline result (feasibility of a common schema: what holds, where it breaks).

## 2. Architecture
Pipeline ingest -> parse -> segment -> extract -> verify -> merge -> evaluate, see README. TODO diagram in `docs/`.

## 3. Use of Apertus
- **Model:** TODO (Apertus v1.5 8B / 70B; state real model and quantisation used)
- **How it is used:** inference, constrained JSON per section/field group, never offsets
- **Where it runs:** TODO (teammate: provider / local llama.cpp)
- Prompts: `src/openparl_extract/extract/prompts/` (versioned). TODO prompt version per result.

## 4. Data
OpenParlData API (published parliamentary material only), corpus list `data/corpus.json`. Raw PDFs are gitignored. TODO final corpus and gold size (state the real number).

## 5. Evaluation
Gold set reviewed with the review app; metrics per field, provenance validity, hallucination rate, feasibility matrix (`data/reports/`).

| Setup | Metric | Result |
|---|---|---|
| 8B | TODO | TODO |
| 70B | TODO | TODO |

Demo question: median days submission -> executive answer for interpellations per parliament (`openparl-extract demo`). TODO result.

## 6. Limitations
TODO. Known: rule-only segmentation (unmatched documents flagged), one primary PDF per affair, API role "Author" is lossy (see `docs/metadata_mapping.md`).

## 7. Reproducibility
TODO hardware, runtime, commit hash, `pytest -q` + commands in README.

## 8. Next steps
Apertus fallback for segmentation, more parliaments, multi-document affairs.

## License
CC-BY-4.0.
