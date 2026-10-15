# bench/  (G3)

`load.py`: 2 companies, 1 and 2 worker pairs, 20 incidents at once. Report p50/p95 memory
read/write latency, incidents per minute, duplicate actions (must be 0), rejected stale writes,
takeovers. `isolation.py`: search every output path (results, history, caches, UI stream)
for the other company's canary; must find 0.
