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

The UI plays only the two outside roles: the world (break a service, change the org chart) and the on-call engineer (confirm or reject, talk in the war room). Switch on "scripted engineer" in Director to let the eval oracle's script answer instead; if nobody answers within 10 minutes, it answers anyway.

## What you see

The page tells one incident as a story, in the order of the learning loop in the plan: **alerts → recall → check → diagnose → page → engineer confirms → learn**. Every animation is a real event appearing in the graph for the first time (a new checkpoint, a claim, a sent action, a trust change); nothing is scripted. With `prefers-reduced-motion`, things appear in their final state.

- **Dependency graph** (centre): services are pills, datastores are squared. Alerting services pulse red; recall paths draw hop by hop from the alerting service to the playbook's datastore (cyan = being checked or applied, dashed = queued or ruled out), labelled "1 hop · same kind of datastore". Playbooks sit on their node as pins showing trust, which counts up when a memory helped. Uninvolved nodes dim. A **checking card** beside the node shows each check passing or failing with the observed value, computed from the investigator's checkpoints with the same measure rules as `memory/playbook.py`. The diagnosed root turns amber, then green once confirmed. Click a node to break it or move its ownership.
- **Caption bar**: one plain sentence for what is happening now (toggle in Director).
- **What happened** (right): the seven steps, each with its evidence. The *check* step is the **Memory Lens**: for every memory considered, *what* it is, *why* it was recalled (pinned or same kind, path, hops, score, trust at use), the *evidence* (each check, pass or fail, observed value, step), and *afterwards* (verdict, trust before → after). When the responder needs the engineer, the **war room** card appears on top: confirm or reject, say how you want to be notified, then answer the read-back. Earlier conversations with the same engineer, and "Where did we leave …?", are under the page step.
- **Agent timeline** (right, second tab): tasks, claims, takeovers, checkpoints and sends in database-clock order, with worker and fencing epoch.
- **Agents** (bottom): inv-1, inv-2 (OS processes), responder and learner. The ring is the time left on the lease; **Kill** sends a real SIGKILL. A killed worker shows `SIGKILL` and its lease draining; the one that takes over shows `e1 → e2`.
- **Timeline strip** (bottom): one dot per stored event; click to jump to it in the Agent timeline.
- **On call** (top right): who is on call per team; the person paged lights up as the envelope reaches them, and the counter shows how many notifications went out (one).
- **Director** (header): scenarios s01–s05, "Kill the investigator after step N" (a one-shot real SIGKILL right after that checkpoint), scripted engineer, captions, on-call changes, plant the wrong playbook (M5), reset.
- **Memory tab**: playbooks (pinned node, source incident, trust, helped · misled, status; click for its checks) and engineer preferences as versioned facts, the approved version superseding the agent's reading.
- **Results tab**: the newest valid eval run in `eval/results/` and the load benchmark.
- **‹›** buttons open the Cypher behind each part in a side panel, with the number of queries and milliseconds the incident view took in FalkorDB.
- **Restart**: if FalkorDB goes away, the stage dims ("FalkorDB restarting…") and the agents wait; when it is back, a toast reports what survived, read back from the graph.

`/classic` keeps the first UI (every panel at once) on the same API.

## The demo, from the UI

1. **s01** (Director): the investigator works from scratch. Confirm in the war room, keeping Priya's line ("for DB saturation, open a ticket with the raw slow-query lines"), then send yes to the read-back.
2. The learner writes a playbook: a pin appears on `postgres-orders` (Memory tab for details).
3. Optional: restart FalkorDB (`docker compose down && docker compose up -d falkordb`); the page dims and recovers.
4. **s04**: switch on *Kill the investigator after step 3* in Director first. The playbook is recalled by kind for `postgres-payments` and checked; after step 3 the holder is SIGKILLed, its lease drains, and the other worker resumes at step 4 under epoch 2. One ticket, citing s01; trust 0.50 → 0.67.
5. **s05**: same checkout symptoms, a bad deploy. The DB playbook is ruled out (`deploys == 0`, observed 1), trust unchanged.
6. **Results** tab.

## API

`GET /api/settings · /api/state · /api/incident/{key} · /api/memory · /api/map · /api/results · /api/recap/{id}`  
`GET /api/db · /api/cypher?path=…`  
`POST /api/break {node | story} · /api/arm-kill {after} · /api/review/{key} {confirmed, message} · /api/reply/{key} {text} · /api/autopilot {on} · /api/workers/{name}/kill · /api/workers/{name}/start · /api/org/on-call {team, person} · /api/org/owner {node, team} · /api/plant-wrong-memory · /api/reset`

If FalkorDB restarts while the UI runs, the agents log one line and wait, the API answers 503, and the page shows a banner until the database is back (demo moment 3 restarts it on camera).

Tests: `tests/test_web.py` drives the same story through `web.demo.Demo` on the graph double and on FalkorDB, including a takeover, and checks every panel's read model and the HTTP API.
