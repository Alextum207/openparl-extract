<!-- FIRST VERSION of the questions prompt (v1). The teammate owns prompt refinement; edit by adding a new vN file. -->
FIELD_GROUP: questions

You are extracting the individual questions asked of the executive (Fragen, questions, domande) from a Swiss parliamentary document. Document language: {language}.

Rules:
- Use ONLY the blocks provided below. Never use outside knowledge.
- Copy every value VERBATIM from the text: no paraphrase, no translation, no summarising. Formatting cleanup is not your job.
- For every value return the `block_id` it came from and the exact `quote`, copied character for character from that block.
- If the information is not clearly present, return null for that value. Do not guess.
- Never invent block ids; use only ids shown in square brackets below.
- Return JSON only, matching the schema, with no extra text.

Return {"questions": [{"id": "q1", "text": {"value", "block_id", "quote"}}, ...]} in document order, one entry per question. A block that contains several questions: one entry per question, each quoting only its own sentence. Return an empty list if there are no questions.

Blocks (one per line, `[block_id] text`):
{blocks}

EXAMPLE (de, invented)
Blocks:
[p1_b2] 1. Wie viele Velowege gibt es? 2. Was kostet der Ausbau?
Output:
{"questions": [{"id": "q1", "text": {"value": "Wie viele Velowege gibt es?", "block_id": "p1_b2", "quote": "Wie viele Velowege gibt es?"}}, {"id": "q2", "text": {"value": "Was kostet der Ausbau?", "block_id": "p1_b2", "quote": "Was kostet der Ausbau?"}}]}

EXAMPLE (fr, invented)
Blocks:
[p1_b2] 1. Combien de pistes cyclables existe-t-il ?
Output:
{"questions": [{"id": "q1", "text": {"value": "Combien de pistes cyclables existe-t-il ?", "block_id": "p1_b2", "quote": "Combien de pistes cyclables existe-t-il ?"}}]}

EXAMPLE (it, invented)
Blocks:
[p1_b2] 1. Quante piste ciclabili esistono?
Output:
{"questions": [{"id": "q1", "text": {"value": "Quante piste ciclabili esistono?", "block_id": "p1_b2", "quote": "Quante piste ciclabili esistono?"}}]}
