# The UI

```bash
make ui            # http://localhost:8000, company_a, demo timing (6 s lease, 2 s heartbeat)
```

One page and a small JSON API (`web/app.py`). Everything on screen is read back from FalkorDB with the queries in `web/queries/`; nothing is kept in the browser.

## What runs

| Process | What it is |
|---|---|
| `web.app` | The page and API; the responder and learner, each in its own claim loop |
| `inv-1`, `inv-2` | Two investigators, each its own OS process (`scripts.run_worker --forever`), started by `web/supervisor.py` |

They share nothing but FalkorDB. The investigators read evidence from the shared simulator (`sim/store.py`: one JSON file per incident under `.sim/`), so either can investigate any incident and take over the other's. The hidden scenario (root, family) never goes into the graph.

The UI plays only the two outside roles: the world (break a service, change the org chart) and the on-call engineer (confirm or reject, talk in the war room). Tick "scripted engineer" to let the eval oracle's script answer instead; if nobody answers within 10 minutes, it answers anyway.

## Panels

- **Company graph:** the dependency graph as stored. Alerting services red, 1 hop orange, 2 hops yellow, the diagnosed root ringed, active playbooks shown as trust badges on the node they are pinned to. The paths recall followed are drawn green (applied) or dashed (ruled out). Click a node to break it or move its ownership.
- **Memory Lens:** while the investigation runs, the memories recall returned and why. After the decision, every memory considered: what (signature, target), why (pinned here or same kind, path, hops, score, trust at use), the evidence (each precondition and step, pass or fail, with the observed value and the step it came from), and what changed (verdict, trust before → after, retired).
- **Agent timeline:** tasks, claims, takeovers, checkpoints and sends in database-clock order, with the worker and fencing epoch of each. The task holding a lease shows a live countdown and a **Kill** button that sends SIGKILL to that worker process.
- **War room:** the notification, what the engineer says, the read-back and the reply, all stored as messages. "Where did we leave …?" answers from the stored conversation.
- **Pager log:** every action sent for the incident (there should be exactly one).
- **Memory tab:** every playbook (trust, helped, misled, pins, sources, checks) and every preference fact, including superseded versions. "Plant a deliberately wrong playbook" sets up the M5 demo.
- **Results tab:** the newest eval run in `eval/results/` and the load benchmark.

## The demo, from the UI

1. **s01**: the investigator works from scratch. Confirm, and keep Priya's line ("for DB saturation, open a ticket with the raw slow-query lines"). Reply yes to the read-back.
2. The learner writes a playbook (Memory tab, and a badge on `postgres-orders`).
3. Optional: restart FalkorDB (`docker compose down && docker compose up -d falkordb`) and `make ui` again.
4. **s04**: the playbook is recalled by kind for `postgres-payments`. After step 3, press **Kill** on the lease; the countdown runs out and the other worker resumes at step 4 under epoch 2. One ticket, citing s01.
5. **s05**: same checkout symptoms, a bad deploy. The Lens shows the DB playbook ruled out (`deploys == 0`, observed 1), trust unchanged.
6. **Results** tab.

## API

`GET /api/settings · /api/state · /api/incident/{key} · /api/memory · /api/map · /api/results · /api/recap/{id}`  
`POST /api/break {node | story} · /api/review/{key} {confirmed, message} · /api/reply/{key} {text} · /api/autopilot {on} · /api/workers/{name}/kill · /api/workers/{name}/start · /api/org/on-call {team, person} · /api/org/owner {node, team} · /api/plant-wrong-memory · /api/reset`

Tests: `tests/test_web.py` drives the same story through `web.demo.Demo` on the graph double and on FalkorDB, including a takeover, and checks every panel's read model and the HTTP API.
