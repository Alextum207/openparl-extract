.PHONY: run demo test

IMAGE ?= openparl-extract
BODY  ?= ZH
LIMIT ?= 3
ARGS  ?=
# .env is optional: without it the defaults in config.py apply (set LLM_BASE_URL / LLM_NAME / LLM_API_KEY for real Apertus runs)
DOCKER_RUN = docker run --rm $(if $(wildcard .env),--env-file .env) -v "$(CURDIR)/data:/app/data" $(IMAGE)

# Full pipeline (ingest -> parse -> segment -> extract -> verify -> merge) for $(LIMIT) affairs of $(BODY),
# then the evaluation and the demo question. Needs a reachable Apertus endpoint (see .env.example).
run:
	docker build -t $(IMAGE) .
	$(DOCKER_RUN) run-all --body-key $(BODY) --limit $(LIMIT) $(ARGS)
	$(DOCKER_RUN) evaluate
	$(DOCKER_RUN) demo

# Plumbing only, no Apertus endpoint needed (mock LLM, quality claims are NOT valid).
demo:
	$(MAKE) run ARGS=--mock

test:
	pip install -e ".[dev]" && pytest -q
