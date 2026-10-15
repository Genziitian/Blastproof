PY ?= python3

.PHONY: install db schema seed test test-live eval eval-rules scenarios lint typecheck check incident story acceptance-1 acceptance-2 persist-write persist-verify

install:
	$(PY) -m pip install -r requirements.txt

db:
	docker compose up -d falkordb

schema:
	$(PY) -m scripts.setup_schema

seed:
	$(PY) -m scripts.seed

# Tests never call a model: LLM_MODEL is blanked so .env cannot switch it on.
test:
	LLM_MODEL= $(PY) -m unittest discover -s tests -p "test_*.py" -v

test-live:
	LLM_MODEL= $(PY) -m unittest tests.test_coord_live tests.test_g1_live tests.test_g2_live tests.test_eval -v

lint:
	ruff check .

typecheck:
	mypy common coord sim tools agents eval scripts memory chat tests/graph_double.py tests/backends.py

check: lint typecheck test

incident:
	$(PY) -m scripts.run_incident --company a --scenario s01

story:
	$(PY) -m scripts.run_incident --company a --scenario s01 s04 s05

acceptance-1:
	TIMING_PROFILE=demo $(PY) -m scripts.acceptance part1 --reset

acceptance-2:
	TIMING_PROFILE=demo $(PY) -m scripts.acceptance part2

persist-write:
	$(PY) -m scripts.persistence_check write

persist-verify:
	$(PY) -m scripts.persistence_check verify

scenarios:
	$(PY) -m eval.scenarios --write

# The benchmark with the configured model (.env). Results in eval/results/<timestamp>/.
eval:
	$(PY) -m eval.run --arms A B C

# The same benchmark with the deterministic planner (no model calls).
eval-rules:
	LLM_MODEL= $(PY) -m eval.run --arms A B C --rule-based
