<!-- FIRST VERSION of the answers prompt (v1). The teammate owns prompt refinement; edit by adding a new vN file. -->
FIELD_GROUP: answers

You are extracting the executive's answers to the questions listed below (Antwort des Regierungsrates, reponse du Conseil d'Etat, risposta del Consiglio di Stato) from a Swiss parliamentary document. Document language: {language}.

Rules:
- Use ONLY the blocks provided below. Never use outside knowledge.
- Copy every value VERBATIM from the text: no paraphrase, no translation, no summarising. Formatting cleanup is not your job.
- For every value return the `block_id` it came from and the exact `quote`, copied character for character from that block.
- If the information is not clearly present, return null for that value. Do not guess.
- Never invent block ids; use only ids shown in square brackets below.
- Return JSON only, matching the schema, with no extra text.

Questions already extracted (id: text):
{questions}

Return {"answers": [{"question_id": "q1" or null, "text": {"value", "block_id", "quote"}}, ...]}. Set question_id to the id of the question the answer belongs to; use null if it is not clearly assignable to one question. One entry per answer. Return an empty list if there are no answers.

Blocks (one per line, `[block_id] text`):
{blocks}

EXAMPLE (de, invented)
Blocks:
[p3_b1] Zu Frage 1: Es gibt 120 km Velowege.
Output:
{"answers": [{"question_id": "q1", "text": {"value": "Es gibt 120 km Velowege.", "block_id": "p3_b1", "quote": "Es gibt 120 km Velowege."}}]}

EXAMPLE (fr, invented)
Blocks:
[p3_b1] Reponse a la question 1 : Il existe 120 km de pistes.
Output:
{"answers": [{"question_id": "q1", "text": {"value": "Il existe 120 km de pistes.", "block_id": "p3_b1", "quote": "Il existe 120 km de pistes."}}]}

EXAMPLE (it, invented)
Blocks:
[p3_b1] Risposta alla domanda 1: Esistono 120 km di piste.
Output:
{"answers": [{"question_id": "q1", "text": {"value": "Esistono 120 km di piste.", "block_id": "p3_b1", "quote": "Esistono 120 km di piste."}}]}
