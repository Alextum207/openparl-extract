<!-- FIRST VERSION of the decision prompt (v1). The teammate owns prompt refinement; edit by adding a new vN file. -->
FIELD_GROUP: decision

You are extracting the decision on the affair: outcome, date and deciding body from a Swiss parliamentary document. Document language: {language}.

Rules:
- Use ONLY the blocks provided below. Never use outside knowledge.
- Copy every value VERBATIM from the text: no paraphrase, no translation, no summarising. Formatting cleanup is not your job.
- For every value return the `block_id` it came from and the exact `quote`, copied character for character from that block.
- If the information is not clearly present, return null for that value. Do not guess.
- Never invent block ids; use only ids shown in square brackets below.
- Return JSON only, matching the schema, with no extra text.

Return {"decision": {"outcome": item, "date": item, "body": item}} where each item is {"value", "block_id", "quote"}.
- outcome: the VALUE is exactly one vocabulary code: adopted, partially_adopted, rejected, withdrawn, written_off, referred_to_executive, no_decision, unknown. The quote is the passage in the text that supports that code (not the code itself).
- date: the VALUE is ISO YYYY-MM-DD when a full date is given, otherwise null. The quote is the passage containing the date.
- body: the deciding body copied verbatim (e.g. the parliament or committee), quote as usual.
Use null for any item that is not clearly present.

Blocks (one per line, `[block_id] text`):
{blocks}

EXAMPLE (de, invented)
Blocks:
[p4_b0] Der Kantonsrat hat die Motion am 12.03.2024 abgelehnt.
Output:
{"decision": {"outcome": {"value": "rejected", "block_id": "p4_b0", "quote": "hat die Motion am 12.03.2024 abgelehnt"}, "date": {"value": "2024-03-12", "block_id": "p4_b0", "quote": "12.03.2024"}, "body": {"value": "Der Kantonsrat", "block_id": "p4_b0", "quote": "Der Kantonsrat"}}}

EXAMPLE (fr, invented)
Blocks:
[p4_b0] Le Grand Conseil a accepte la motion le 5 mars 2024.
Output:
{"decision": {"outcome": {"value": "adopted", "block_id": "p4_b0", "quote": "a accepte la motion"}, "date": {"value": "2024-03-05", "block_id": "p4_b0", "quote": "5 mars 2024"}, "body": {"value": "Le Grand Conseil", "block_id": "p4_b0", "quote": "Le Grand Conseil"}}}

EXAMPLE (it, invented)
Blocks:
[p4_b0] Il Gran Consiglio ha respinto la mozione.
Output:
{"decision": {"outcome": {"value": "rejected", "block_id": "p4_b0", "quote": "ha respinto la mozione"}, "date": {"value": null, "block_id": null, "quote": null}, "body": {"value": "Il Gran Consiglio", "block_id": "p4_b0", "quote": "Il Gran Consiglio"}}}
