<!-- FIRST VERSION of the affair_text prompt (v1). The teammate owns prompt refinement; edit by adding a new vN file. -->
FIELD_GROUP: affair_text

You are extracting the text of the parliamentary affair itself (the motion, postulate, interpellation or question as submitted) from a Swiss parliamentary document. Document language: {language}.

Rules:
- Use ONLY the blocks provided below. Never use outside knowledge.
- Copy every value VERBATIM from the text: no paraphrase, no translation, no summarising. Formatting cleanup is not your job.
- For every value return the `block_id` it came from and the exact `quote`, copied character for character from that block.
- If the information is not clearly present, return null for that value. Do not guess.
- Never invent block ids; use only ids shown in square brackets below.
- Return JSON only, matching the schema, with no extra text.

Return {"affair_text": {"value", "block_id", "quote"}}. Pick the single block that holds the submitted text; if it spans several blocks, use the first one and quote only what is in that block.

Blocks (one per line, `[block_id] text`):
{blocks}

EXAMPLE (de, invented)
Blocks:
[p1_b1] Der Regierungsrat wird beauftragt, die Velowege auszubauen.
Output:
{"affair_text": {"value": "Der Regierungsrat wird beauftragt, die Velowege auszubauen.", "block_id": "p1_b1", "quote": "Der Regierungsrat wird beauftragt, die Velowege auszubauen."}}

EXAMPLE (fr, invented)
Blocks:
[p1_b1] Le Conseil d'Etat est charge de developper les pistes cyclables.
Output:
{"affair_text": {"value": "Le Conseil d'Etat est charge de developper les pistes cyclables.", "block_id": "p1_b1", "quote": "Le Conseil d'Etat est charge de developper les pistes cyclables."}}

EXAMPLE (it, invented)
Blocks:
[p1_b1] Il Consiglio di Stato e incaricato di potenziare le piste ciclabili.
Output:
{"affair_text": {"value": "Il Consiglio di Stato e incaricato di potenziare le piste ciclabili.", "block_id": "p1_b1", "quote": "Il Consiglio di Stato e incaricato di potenziare le piste ciclabili."}}
