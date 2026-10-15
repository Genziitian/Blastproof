# Blast Radius

On-call agents that remember previous incidents, check whether that memory still applies, and show how it changed the next investigation, even after a restart. Graph Hacks 2026, Track 02 (Agent Memory and Coordination). FalkorDB holds the memory, the shared task state and the evidence trail.

> Work in progress. This README becomes the submission version on Sunday.

## Status

| Gate | What | State |
| --- | --- | --- |
| G1 | Simulator, three failure families, truth files, oracle | Done; offline tests pass |
| G1 | Tool registry (7 tools) + MCP server | Done offline; MCP server not yet run |
| G1 | Fenced coordination, triage, investigator, responder | Runs end to end on the graph double; not yet on FalkorDB |
| G2 | Graph recall (A1, A1b), playbooks with preconditions (A4), trust from per-memory verdicts (A2) | Runs end to end on the graph double; not yet on FalkorDB |
| G2 | Learner worker, war-room chat, conditional preferences (A3), guarded LLM planner | Runs end to end on the graph double; not yet on FalkorDB |
| G2 | Acceptance test with a real process kill | `make acceptance-1`, restart, `make acceptance-2` |
| G2 | 30-scenario eval with arms A, B, C | Not started |
| G3 | Load and isolation bench, UI | Not started |

## Run it

Requires Docker and Python 3.10+. Run everything from this folder.

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env

make db          # FalkorDB on :6379, Browser on http://localhost:3000
make schema      # indexes + unique constraints; waits until all are OPERATIONAL
make seed        # explicit; nothing reseeds on startup
make test        # unit tests + every integration suite on the in-memory graph double
make test-live   # coordination, G1 and G2 suites on the double and on FalkorDB
make story       # s01 -> s04 -> s05 with reports: learn, transfer, rule out
```

The acceptance test (the plan's seven steps):

```bash
make acceptance-1
docker compose down && docker compose up -d falkordb
make acceptance-2
```

`make check` runs ruff, mypy and the tests.

The integration suites are written once and run on two backends: FalkorDB when it is
reachable, and `tests/graph_double.py` always. The double runs each query's Python twin
and checks every call against the real `.cypher` file (parameters, RETURN columns,
property types), so a mismatch between code and query fails offline. Only FalkorDB
proves the Cypher itself.

### LLM (optional, free)

Everything runs without a model. To let an LLM plan the investigation and read the engineer's messages, point `.env` at any OpenAI-compatible endpoint, e.g. a local [Ollama](https://ollama.com) model: `LLM_MODEL=gemma4:e4b`. Any invalid model answer falls back to the rule-based planner, so the run can't derail.

## How an incident runs

1. **Triage** turns alerts into an `Incident` and an `investigate` task.
2. **Investigator** recalls playbooks pinned near the alerting services (graph proximity, not text similarity) and checks each one's preconditions against live evidence. The first that holds is the diagnosis; otherwise it investigates with the planner. Every tool call is checkpointed first, so a replacement worker resumes at the next step. The `Decision` records every memory it considered, with the evidence for and against.
3. **Responder** notifies the on-call engineer, in the way they asked for this kind of incident, citing the message where they asked. The notification is keyed by intent, so it is sent once. What the engineer says is stored verbatim; instructions become preferences after a read-back.
4. **Learner** gives each memory used a verdict (helped, misled, or not applicable), updates trust, and turns a confirmed investigation into a sourced candidate playbook.

## Rules the code keeps

- **One graph per company**, chosen from trusted config, never by the model.
- **Two clocks:** `timestamp()` inside queries for leases; scenario time for evidence, validity and `recorded_at`.
- **Every task write is fenced** on status, epoch, owner and lease expiry, and returns `ok`, `already_done` or `lease_lost`.
- **Memory is never edited:** facts are superseded, playbooks gain sources, trust moves only on verdicts.
- **Ground truth lives only in `eval/truth/`.** `tests/test_boundaries.py` fails if agent-side code imports `eval`.

## Layout

| Path | Contents |
| --- | --- |
| `agents/` | Worker loop, triage, planners, investigator, responder, learner |
| `memory/` | Recall, playbooks, templates, verdicts, fact writes, and their queries |
| `chat/` | War-room sessions and preference extraction |
| `coord/` | Fenced task coordination and its queries |
| `tools/` | Tool registry, graph tools, MCP server |
| `sim/` | Synthetic company, incident simulator, runtime |
| `eval/` | Truth files and the oracle |
| `scripts/` | Schema, seed, runners, acceptance test, persistence check |
| `tests/` | Offline tests and live tests against FalkorDB |

Every query the product depends on is a `.cypher` file in a `queries/` folder.

## AI assistance

To be completed before submission: which AI coding assistants were used, and for what.
