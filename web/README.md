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

## Pages

| Address | Page |
|---|---|
| `/` | **Landing page.** The idea in five stages (remember, recall, check, act, learn), told with live data: the hero replays a real incident from the graph, the check cards, playbooks, preferences and results are read from the API, and the Cypher card shows the real recall query. Until this machine has run its own incidents, a recorded run (`web/static/example.json`) stands in and is labelled *recorded run*. |
| `/mission-control` | **Mission control, the live demo.** Break a service and watch the agents work. (`/war-room` redirects here.) |
| `/dark`, `/classic` | Earlier views on the same API, kept as fallbacks. |
| `/blog/` | **The write-up** (`docs/blog/`), the same page published on GitHub Pages. |

Shared code: `web/static/core.js` turns an incident's stored records into what the pages show (steps, checks computed with the same measure rules as `memory/playbook.py`, captions, takeovers, trust, and a replay of any moment); `web/static/v2.css` is the look.

## Mission control

The incident is told in the order of the learning loop in the plan: **alerts → recall → check → diagnose → page → engineer confirms → learn**. Every animation is a real event appearing in the graph for the first time (a checkpoint, a claim, a sent action, a trust change); with `prefers-reduced-motion`, things appear in their final state.

- **Left:** the incident, a headline for what is happening now, and the seven steps with their evidence. The *check* step is the **Memory Lens**: for every memory considered, *what* it is, *why* it was recalled, the *evidence* (each check, pass or fail, observed value, step), and *afterwards* (verdict, trust before → after). When the responder needs the engineer, the **war room** card appears under the headline: confirm or reject, say how you want to be notified, then answer the read-back. Earlier conversations with the same engineer and "Where did we leave …?" are under the confirmation step. Below: the **agents**, with lease rings, **Kill** (a real SIGKILL) and **Start**.
- **Right:** the service graph. Alerting services pulse; recall paths draw hop by hop, with a dashed line to where a playbook was learned when it was recalled by kind; pins show each playbook's trust and count up when it helped. A **checking card** ticks off each check from the investigator's checkpoints. Click a node to break it or move its ownership. Above: on call now and the notification count; the envelope flies to the person paged. Below: one sentence for what is happening and the five-stage strip.
- **← ▶ →** replays the selected incident from its stored steps (claims, checkpoints, the takeover, the page, the learning); **Live** returns to the live view.
- **Director:** scenarios s01–s05, "Kill the investigator after step N" (one-shot real SIGKILL), scripted engineer, on-call changes, plant the wrong playbook (M5), reset.
- **Memory tab:** playbooks (pinned node, source incident, trust, helped · misled, status; click for checks) and engineer preferences as versioned facts. **Results tab:** the newest valid eval run and the load benchmark.
- **{ } query** buttons open the Cypher behind each part, with the number of queries and milliseconds the incident view took in FalkorDB.
- **Restart:** if FalkorDB goes away, the graph card dims (*FalkorDB restarting…*) and the agents wait; when it is back, a toast reports what survived, read back from the graph.

## The demo, from the UI

1. Open `/`, then **Enter mission control**. **s01** (Director): the investigator works from scratch. Confirm in the war room, keeping Priya's line ("for DB saturation, open a ticket with the raw slow-query lines"), then send yes to the read-back.
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
