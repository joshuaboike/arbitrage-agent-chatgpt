PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup test lint run-api run-ingest run-normalize run-underwrite run-alerts run-craigslist-smoke run-craigslist-stage1 run-craigslist-stage2 run-craigslist-stage3 run-craigslist-stage4

setup:
	$(PYTHON) -m pip install -e .[dev]

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check scanner tests

run-api:
	$(PYTHON) -m uvicorn scanner.apps.api.main:app --reload

run-ingest:
	$(PYTHON) -m scanner.apps.worker_ingest.main

run-normalize:
	$(PYTHON) -m scanner.apps.worker_normalize.main

run-underwrite:
	$(PYTHON) -m scanner.apps.worker_underwrite.main

run-alerts:
	$(PYTHON) -m scanner.apps.worker_alerts.main

run-craigslist-smoke:
	$(PYTHON) -m scanner.apps.worker_ingest.craigslist_smoke

run-craigslist-stage1:
	$(PYTHON) -m scanner.apps.worker_underwrite.craigslist_stage1

run-craigslist-stage2:
	$(PYTHON) -m scanner.apps.worker_underwrite.craigslist_stage2

run-craigslist-stage3:
	$(PYTHON) -m scanner.apps.worker_underwrite.craigslist_stage3

run-craigslist-stage4:
	$(PYTHON) -m scanner.apps.worker_underwrite.craigslist_stage4
