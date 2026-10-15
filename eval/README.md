# eval/  (G2 → G3)

- `truth/` : scenario answers. Evaluator-only: never written to FalkorDB, never in a prompt.
- `scenarios.py` (G2): 30 scenarios (6 cold start on empty snapshots, 6 repeat with new wording,
  6 related service, 6 same symptom / different cause, 3 no applicable memory, 3 org change) + the M5 scenario.
- `oracle.py` (G1): reads truth, confirms or rejects a diagnosis through the same feedback API as the UI.
- `run.py` (G2): arms A (no memory), B (text retrieval), C (graph retrieval), each in its own graph
  (`eval_a`, `eval_b`, `eval_c`), same model, temperature 0, same budgets.
- `results/` (G3): numbers frozen by Sat 9 PM. Timings from an UNCACHED run only.
