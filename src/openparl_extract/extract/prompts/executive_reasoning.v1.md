<!-- FIRST VERSION of the executive_reasoning prompt (v1). The teammate owns prompt refinement; edit by adding a new vN file. -->
FIELD_GROUP: executive_reasoning

You are extracting the general reasoning or position of the executive (Regierungsrat, Conseil d'Etat, Consiglio di Stato) that is not an answer to one specific question from a Swiss parliamentary document. Document language: {language}.

Rules:
- Use ONLY the blocks provided below. Never use outside knowledge.
- Copy every value VERBATIM from the text: no paraphrase, no translation, no summarising. Formatting cleanup is not your job.
- For every value return the `block_id` it came from and the exact `quote`, copied character for character from that block.
- If the information is not clearly present, return null for that value. Do not guess.
- Never invent block ids; use only ids shown in square brackets below.
- Return JSON only, matching the schema, with no extra text.

Return {"executive_reasoning": {"value", "block_id", "quote"}}. Use the single block that best holds the general reasoning.

Blocks (one per line, `[block_id] text`):
{blocks}

EXAMPLE (de, invented)
Blocks:
[p3_b0] Der Regierungsrat erachtet den Ausbau als nicht vordringlich.
Output:
{"executive_reasoning": {"value": "Der Regierungsrat erachtet den Ausbau als nicht vordringlich.", "block_id": "p3_b0", "quote": "Der Regierungsrat erachtet den Ausbau als nicht vordringlich."}}

EXAMPLE (fr, invented)
Blocks:
[p3_b0] Le Conseil d'Etat estime que l'extension n'est pas prioritaire.
Output:
{"executive_reasoning": {"value": "Le Conseil d'Etat estime que l'extension n'est pas prioritaire.", "block_id": "p3_b0", "quote": "Le Conseil d'Etat estime que l'extension n'est pas prioritaire."}}

EXAMPLE (it, invented)
Blocks:
[p3_b0] Il Consiglio di Stato ritiene che il potenziamento non sia prioritario.
Output:
{"executive_reasoning": {"value": "Il Consiglio di Stato ritiene che il potenziamento non sia prioritario.", "block_id": "p3_b0", "quote": "Il Consiglio di Stato ritiene che il potenziamento non sia prioritario."}}
