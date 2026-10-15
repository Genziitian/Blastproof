# bench/

- `load.py` (M8): two companies, every worker (investigator, responder, learner) in its own
  claim loop, 20 incidents fired at once. Runs with 1 and 2 worker pairs per company, then 2
  pairs while a chaos thread expires a held lease every 50 ms (a stalled worker). Reports
  p50/p95 memory read and write latency, incidents per minute, duplicate notifications (must
  be 0), takeovers, lost leases, and tasks left for a human after 3 attempts. `make bench`.
- `isolation.py` (M9): identical service names, keys and incident ids in two companies;
  searches every stored string in each graph for the other company's canary and people,
  checks preferences don't cross, and that no model-callable tool takes a graph argument.
  `make isolation`.

Both use the deterministic planner: they measure FalkorDB and the coordination protocol,
not a model. Results go to `bench/results/`.
