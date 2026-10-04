<!-- FIRST VERSION of the justification prompt (v1). The teammate owns prompt refinement; edit by adding a new vN file. -->
FIELD_GROUP: justification

You are extracting the justification / reasoning given by the submitters for their affair (Begruendung, developpement, motivazione) from a Swiss parliamentary document. Document language: {language}.

Rules:
- Use ONLY the blocks provided below. Never use outside knowledge.
- Copy every value VERBATIM from the text: no paraphrase, no translation, no summarising. Formatting cleanup is not your job.
- For every value return the `block_id` it came from and the exact `quote`, copied character for character from that block.
- If the information is not clearly present, return null for that value. Do not guess.
- Never invent block ids; use only ids shown in square brackets below.
- Return JSON only, matching the schema, with no extra text.

Return {"justification": {"value", "block_id", "quote"}}. Use the single block that best holds the justification.

Blocks (one per line, `[block_id] text`):
{blocks}

EXAMPLE (de, invented)
Blocks:
[p2_b0] Begruendung: Der Veloverkehr nimmt jaehrlich zu.
Output:
{"justification": {"value": "Der Veloverkehr nimmt jaehrlich zu.", "block_id": "p2_b0", "quote": "Der Veloverkehr nimmt jaehrlich zu."}}

EXAMPLE (fr, invented)
Blocks:
[p2_b0] Developpement: Le trafic cycliste augmente chaque annee.
Output:
{"justification": {"value": "Le trafic cycliste augmente chaque annee.", "block_id": "p2_b0", "quote": "Le trafic cycliste augmente chaque annee."}}

EXAMPLE (it, invented)
Blocks:
[p2_b0] Motivazione: Il traffico ciclistico aumenta ogni anno.
Output:
{"justification": {"value": "Il traffico ciclistico aumenta ogni anno.", "block_id": "p2_b0", "quote": "Il traffico ciclistico aumenta ogni anno."}}
