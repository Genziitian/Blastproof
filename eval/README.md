# eval/

Evaluator-only code. Nothing the agents run imports this package (`tests/test_boundaries.py`).

- `scenarios.py`: the benchmark definition. 30 incidents replayed in time order
  (6 cold, 6 repeat with unseen wording, 6 related sibling datastore, 6 same symptom /
  different cause, 3 no applicable memory, 3 org change) plus M5, a deliberately wrong
  playbook. `make scenarios` writes them to `truth/`; a test fails if the files drift.
- `truth/`: the answers (root, family, who should be notified and how, org changes).
  Never written to FalkorDB, never in a prompt.
- `oracle.py`: plays the on-call engineer; confirms or rejects through the same API as the UI.
- `run.py`: replays the benchmark per arm, each in its own graph (`eval_a`, `eval_c`),
  same planner, model, tools and oracle. Arm B (text retrieval) lands on Saturday.
- `queries/`: the scorer's read-only Cypher.
- `results/<run>/`: `rows.jsonl` (one row per incident), `summary.json`, `summary.md`.

```bash
make eval-rules   # deterministic planner, no model calls, ~5 s
make eval         # the configured model (.env); set LLM_CACHE_DIR only for reruns
```

Timings and the speed-up claim come from an uncached run only.
