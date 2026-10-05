# Schema mapping (v0.1) to existing standards

Draft by the authors from general knowledge of the standards; element names are **proposals to be checked** against the
specs before the 12 Oct freeze. "none" means we found no natural counterpart. Our model: `src/openparl_extract/models.py`.

| Our concept | Akoma Ntoso | Popolo | Parla-CLARIN | Docling |
|---|---|---|---|---|
| `Affair` (whole object) | `<doc name="...">` / `<act>` metadata | Motion / Event | none (debate transcripts, not affairs) | `DoclingDocument` (generic) |
| `affair_type`, `original_type_label` | `<FRBRWork>` `name` + `<TLCConcept>` | Motion `classification` | none | none |
| `reference_number` | `<FRBRthis>` / `<FRBRalias>` | `identifier` | `<idno>` | none |
| `title` | `<docTitle>` | `name` | `<title>` | `title` / section header item |
| `actors[role=submitter/co_signatory]` | `<TLCPerson>` + `<FRBRauthor as="#...">` | `Person`, `Membership`, Motion `creator`/`sponsor` | `<person>` / `<speaker>` | none |
| `actors[].party / faction` | `<TLCOrganization>` | `Organization` (`classification`: party / faction) | `<affiliation>` | none |
| `addressed_body` | `<TLCOrganization>` (addressee) | `Organization` | none | none |
| `affair_text`, `justification` | `<body>` / `<preface>` / `<blockContainer>` | none (text not modelled) | `<div>` | `texts[]` with `label` |
| `questions[]` / `answers[]` | `<question>` / `<answer>` structures (only partly standardized) | none | `<u>` (utterance) in a Q&A sequence | `texts[]` |
| `decision.outcome / date / body` | `<lifecycle>` `<eventRef>` + `<step>` | Motion `result`, `VoteEvent` | none | none |
| `procedural_history[]` | `<lifecycle>` `<eventRef>` | `Event` | `<head>` / `<note>` | none |
| `related_affairs[]` | `<references>` / `<ref>` | `Relation` (loose) | none | none |
| `annexes`, `tables`, `images` | `<attachments>`, `<table>`, `<img>` | none | none | `tables[]`, `pictures[]` |
| `Provenance.page / block_id / quote` | none (no per-value source anchors) | `sources[]` (url only) | `@source` / `@facs` (page-level) | `prov[]` (page, bbox) |
| `Value.status` (extracted / from_metadata / inferred / not_found) | none | none | none | none |

Observations (for the report):
- The per-value `status` and span-level provenance have **no equivalent** in any of the four: this is our main addition.
- Parla-CLARIN covers speeches, not affairs; Popolo covers actors and votes but not document text; Akoma Ntoso covers
  all of it but is heavy for a municipality. This is the "middle layer" gap from the challenge.
- Our block IDs (`p{page}_b{index}`) map one-to-one to Docling items (`prov.page_no` + item order).
