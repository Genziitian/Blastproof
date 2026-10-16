# Blast Radius

On-call agents that remember previous incidents, check whether that memory still applies, and show how it changed the next investigation, even after a restart.

Graph Hacks 2026 · Track 02 (Agent Memory and Coordination). FalkorDB holds the memory, the shared task state between agents, the conversation history and the evidence trail; take it out and nothing works.

> Work in progress: updated as each piece lands. Last update: Fri Oct 16, 2026 (the UI: Memory Lens, agent timeline, war room, kill button).

## Results

A 30-incident synthetic benchmark replayed in time order. Three setups, each in its own graph, with the same model (Claude Haiku 5.5), tools, step budget (12), oracle and learning; **only how memories are retrieved differs**:

- **A, no memory:** always investigates from scratch.
- **B, text memory:** tries the memories whose text is most similar to the alerts (embedding similarity, FalkorDB `vec.cosineDistance`).
- **C, graph memory:** tries the memories pinned near the alerting services in the dependency graph.

Run on Oct 16 (results in `eval/results/2026-10-15T19-15-28Z-claude-haiku-5-5/`, uncached):

| | A: no memory | B: text memory | C: graph memory |
|---|---|---|---|
| Root cause correct | 30/30 | 29/30 | **30/30** |
| LLM requests, whole benchmark | 185 | 101 (−45%) | **52 (−72%)** |
| Input / output tokens | 438k / 60k | 251k / 31k | **128k / 18k** |
| Wall-clock time, whole benchmark | 417 s | 219 s | **127 s** |
| Incidents solved from memory | 0 | 10 | **21** |
| Repeat incidents: LLM requests, seconds each | 6.0, 13.5 s | 1.7, 4.0 s | **0, 0.02 s** |
| Related-service incidents: LLM requests, seconds each | 5.5, 12.7 s | 2.5, 5.2 s | **0, 0.02 s** |
| Same symptom, different cause: LLM requests, seconds each | 6.3, 14.0 s | 3.0, 6.9 s | **0, 0.02 s** |
| Recall@5 of a memory that gives the right answer (21 incidents where one exists, same snapshot) | n/a | 48% | **100%** |
| Times a memory misled the agent | n/a | 0 | 0 |
| Right person paged after an on-call or ownership change | 3/3 | 3/3 | 3/3 |
| Duplicate notifications | 0 | 0 | 0 |
| M5: a deliberately wrong playbook | n/a | n/a | misled twice, retired, next incident correct |

Approximate model cost for the whole benchmark: A $0.04, B $0.02, C $0.01 (most input tokens are prompt-cache reads).

What this does and doesn't show:

- **Same accuracy, far less work.** Claude Haiku 5.5 already solves this benchmark from scratch, so memory can't raise accuracy here. Graph memory gives the same answers with 72% fewer model requests, and with no model call at all for 21 of 30 incidents.
- **Text memory finds the right memory half as often.** When a memory that gives the right answer exists, text similarity ranks it in the top 5 for 48% of incidents, graph proximity for 100%: "which node is failing near these alerts" is a question about the dependency graph, not about wording.
- **Checking the wrong memories has a cost.** Every recalled memory is checked against live evidence before it is trusted, so no arm was ever misled; but checks take steps. Arm B lost one incident (e20) this way: it checked five wrong memories, and the model ran out of the 12-step budget before concluding. On cold and novel incidents, graph memory also takes more steps than no memory (about 8 vs 6), though fewer model calls.
- **Caveat on B:** text is embedded with a deterministic hashed bag of words; a neural embedder (`EMBED_MODEL`, e.g. Gemini's) is supported and a fairer opponent.
- **Synthetic benchmark only.** A 15-node company and three failure families; the results describe this benchmark and nothing more. The same run with the deterministic planner (no model) is in `eval/results/` too.

FalkorDB finding (persistence): on FalkorDB 4.22.1, after a day of development (eval runs and benchmarks that delete and re-create graphs), restarting replayed the append-only file and failed with `GRAPH.EFFECT references label/relationship-type 'Memory' (id 0) which doesn't match local schema state`, then shut itself down on every start. The same reset-then-restart sequence replayed fine on 4.18.3. We now persist with RDB snapshots (every 30 s and on shutdown), which load without replay; the acceptance test's restart passes all seven checks this way.

FalkorDB finding: on graphs this small, the HNSW vector index (`db.idx.vector.queryNodes`) returned fewer neighbours than requested (1 to 2 of 3 embedded memories for k = 10), so arm B uses exact `vec.cosineDistance` instead.

### Concurrency and tenant isolation (M8, M9)

Two companies, every agent in its own claim loop, 20 incidents fired at once, FalkorDB in Docker on one laptop-class machine, deterministic planner (this measures FalkorDB and the coordination protocol, not a model). `make bench`, `make isolation`.

| Worker pairs per company | Stalled workers | Done | Incidents / min | Memory reads p50 / p95 | Memory writes p50 / p95 | Duplicate notifications | Takeovers |
|---|---|---|---|---|---|---|---|
| 1 | none | 20/20 | ~1,900–2,600 | ~2 / 5–7 ms | ~2–3 / 5–7 ms | 0 | 0 |
| 2 | none | 20/20 | ~2,500–3,100 | ~2–3 / 7–9 ms | ~3 / 9 ms | 0 | 0 |
| 2 | a held lease expired every 50 ms | 20/20 | ~2,000–2,600 | ~3 / 8–9 ms | ~3 / 8–10 ms | **0** | 6–7 |

Ranges are across runs. With stalled workers, another worker takes the task over at the next checkpoint and the stalled one's next write is rejected by the fence (6–8 lost leases per run), and still nothing is sent twice. Isolation: identical service names, keys and incident ids in both companies; every stored string in each graph is searched for the other company's canary and people: 0 found. Priya's "tickets for DB saturation" in company A never reaches the Priya of company B. No tool the model can call takes a graph or company argument.


## How it works

1. **Triage** turns alerts into an `Incident` and an `investigate` task.
2. **Investigator** recalls playbooks pinned near the alerting services by walking the dependency graph downstream (A1), or pinned to another datastore of the same kind (A1b). It checks each recalled playbook's preconditions and steps against live evidence, without the model; the first that holds is the diagnosis. Otherwise it investigates with the LLM planner (guard-railed by a rule-based planner). Every tool call is checkpointed before the next one, so a replacement worker resumes at the next step.
3. **Responder** notifies whoever owns the failing node and is on call *at the incident's time*, the way that person asked for this kind of incident, citing the message where they asked. The notification is keyed by intent, so it is sent once. What the engineer says is stored verbatim; instructions are read back and only become approved preferences after a yes.
4. **Learner** gives each memory used a verdict (helped, misled, not applicable), updates trust, retires memories that keep misleading, and turns a confirmed investigation into a sourced playbook (or pins an existing one to the new root).

The `Decision` records every memory considered, with the evidence for and against, so "what did the agent believe then, and why?" is a query, not a guess.

### Memory algorithms (all Cypher in `*/queries/`)

| | What | Where |
|---|---|---|
| A1 | Downstream recall with paths; score = trust × age decay × Σ over alerting services of 0.5^hops | `memory/queries/recall*.cypher`, `memory/recall.py` |
| A2 | Trust from per-memory verdicts; retire when misled ≥ 2 and trust < 0.5 | `memory/queries/feedback.cypher` |
| A3 | Facts change by supersession, never by edit (preferences, approvals) | `memory/queries/fact_*.cypher` |
| A4 | Candidate playbook from a confirmed run, with machine-checkable preconditions | `memory/templates.py`, `memory/queries/write_playbook.cypher` |
| Org | On-call and ownership changes close the old edge and open a new one | `sim/queries/` |

### Coordination

Fenced leases (status, epoch, owner, `lease_until >= timestamp()`), synchronous idempotent checkpoints, intent-keyed actions, derived-id handoffs, an attempts limit and a stuck sweep. Every write returns `ok`, `already_done` or `lease_lost`. The acceptance test SIGKILLs a real worker process after checkpoint 3; the replacement resumes at 4 and exactly one notification goes out.

## Run it

Requires Docker and Python 3.10+. Run everything from this folder.

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env     # settings are read from .env automatically

make db          # FalkorDB (Browser on http://localhost:3000)
make schema      # indexes + unique constraints; waits until all are OPERATIONAL
make seed        # explicit; nothing reseeds on startup
make test        # unit tests + every integration suite on the in-memory graph double
make test-live   # the integration suites and the benchmark on FalkorDB too
make story       # s01 -> s04 -> s05: learn, transfer to a sibling, rule out on evidence
```

If something else already listens on port 6379 (a local Redis), set `FALKORDB_PORT=6380` in `.env`; Docker Compose and the Python client both read it.

The UI (Memory Lens, agent timeline with a kill button, war room, company graph, results):

```bash
make ui          # http://localhost:8000, demo timing: 6 s lease, 2 s heartbeat (labelled on screen)
```

It runs two investigators as separate processes (Kill sends a real SIGKILL), plus the responder and learner, and reads everything back from FalkorDB. You play the on-call engineer in the war room, or tick "scripted engineer". Panels and the demo walkthrough: [`web/README.md`](web/README.md).

The acceptance test (seven checks, real process kill, full restart):

```bash
make acceptance-1      # resets company_a, runs s01, learns a playbook
docker compose down && docker compose up -d falkordb
make acceptance-2      # s04 after the restart, SIGKILL mid-investigation, takeover
```

Persistence: FalkorDB writes an RDB snapshot every 30 s if anything changed and on every shutdown, into a named Docker volume; nothing reseeds on startup. `make acceptance-2` (and the UI) wait until FalkorDB has finished loading after a restart. We started with the append-only file (AOF) and switched: see the FalkorDB findings below.

The benchmark:

```bash
make eval-rules   # arms A, B, C with the deterministic planner, no model calls, seconds
make eval         # arms A, B, C with the configured model; eval/results/<timestamp>/
```

### Model

Everything runs without a model (rule-based planner and preference parser). With a model, the investigator plans with it and the war room reads the engineer's messages with it; any invalid answer falls back to the rule-based step.

- **Claude** (what the results above use): `LLM_BASE_URL=https://api.anthropic.com`, `LLM_MODEL=claude-haiku-5-5`, `LLM_API_KEY=...`. Uses the native Messages API with prompt caching: tools, instructions and every earlier step are re-read from cache on each turn.
- **Any OpenAI-compatible endpoint** (Gemini, DeepSeek, Groq, OpenAI, Ollama): set base URL, model and key; see `.env.example`.

## Tests

The integration suites are written once and run on two backends: FalkorDB when it is reachable, and `tests/graph_double.py` always. The double runs each query's Python twin and checks every call against the real `.cypher` file (parameters, RETURN columns, property types). Only FalkorDB proves the Cypher itself, and it has caught things the double could not (FalkorDB evaluates back-to-back `SET` clauses against the pre-update values).

## Rules the code keeps

- **One graph per company**, chosen from trusted config, never by the model.
- **Two clocks:** `timestamp()` inside queries for leases; scenario time for evidence, validity and `recorded_at`.
- **Every task write is fenced** and returns `ok`, `already_done` or `lease_lost`.
- **Memory is never edited:** facts are superseded, playbooks gain sources, trust moves only on verdicts.
- **Ground truth lives only in `eval/truth/`.** `tests/test_boundaries.py` fails if agent-side code imports `eval`.

## Layout

| Path | Contents |
| --- | --- |
| `agents/` | Worker loop, triage, planners, investigator, responder, learner |
| `memory/` | Recall, playbooks, templates, verdicts, fact writes, and their queries |
| `chat/` | War-room sessions, preference extraction, recap |
| `coord/` | Fenced task coordination and its queries |
| `tools/` | Tool registry, graph tools, MCP server |
| `sim/` | Synthetic company, incident simulator (in-process, or shared between processes via `sim/store.py`), org changes |
| `eval/` | Benchmark definition, truth files, oracle, runner, results |
| `bench/` | Load benchmark with stalled workers, tenant-isolation check |
| `web/` | The UI: one page, a JSON API, its read queries, the investigator supervisor |
| `scripts/` | Schema, seed, runners, acceptance test, persistence check |
| `tests/` | Offline tests and live tests against FalkorDB |
| `docs/` | The implementation plan |

## Still to come

Arm B with a neural embedder · demo GIF and video · final frozen numbers (Sat 9 PM).

## AI assistance

AI coding assistants were used and are disclosed here, as the rules require. Draft, to be confirmed by the team before submission:

- **Claude (Anthropic)**: pair-programming on most of the code, tests and this README, live verification against FalkorDB, and review of the plan.
- **ChatGPT and Gemini**: independent reviews of the implementation plan (three rounds; their findings and our decisions are listed in `docs/Implementation-Plan.md`).
- **Claude Haiku 5.5** is also part of the product: it plans investigations and reads engineers' messages at runtime.

The design (graph model, memory algorithms, coordination protocol, benchmark) and every decision in the plan were made and verified by the team.
