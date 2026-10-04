# Task 1 report
Implemented models.py, extract/schemas.py, extract/llm_client.py, tests, schema/affair.v0.1.json per rulings.
RED: `.venv/Scripts/python -m pytest -q` -> 2 collection errors (ModuleNotFoundError openparl_extract.extract.schemas).
GREEN: same command -> 24 passed.
Concerns: Actor.party/faction and several Affair fields are optional with None default (rulings did not specify); RelatedAffair = {reference: Value[str], openparldata_id}. Mock only records calls when a known group is found.
