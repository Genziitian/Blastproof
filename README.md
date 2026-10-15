# Blast Radius

On-call agents that remember previous incidents, check whether that memory still applies, and show how it changed the next investigation, even after a restart.

Graph Hacks 2026 · Track 02 (Agent Memory and Coordination). FalkorDB holds the memory, the shared task state between agents, the conversation history and the evidence trail; take it out and nothing works.

> Work in progress: updated as each piece lands. Last update: Fri Oct 16, 2026.

## Results so far (preliminary)

A 30-incident synthetic benchmark replayed in time order, each setup in its own graph, same model (Claude Haiku 5.5), same tools, same oracle. Only memory access differs. Run on Oct 16 at commit `ef33331`; files in `eval/results/`.

| | A: no memory | C: graph memory |
|---|---|---|
| Root cause correct | 30/30 | 30/30 |
| LLM requests, whole benchmark | 198 | **51** (−74%) |
| Input / output tokens | 473k / 65k | **124k / 16k** |
| Wall-clock time, whole benchmark | 451 s | **116 s** |
| Repeat incidents (6): LLM requests, time per incident | 6.0, 13.8 s | **0, 0.02 s** |
| Related-service incidents (6): LLM requests, time per incident | 6.2, 14.4 s | **0, 0.02 s** |
| Same symptom, different cause (6) | investigated | 6/6 from memory; the wrong kind of playbook ruled out on evidence 5 times, misled 0 times |
| Memory applied where none fit (novel, 3) | n/a | 0 |
| Right person paged after an on-call or ownership change | 3/3 | 3/3 |
| Duplicate notifications | 0 | 0 |
| M5: a deliberately wrong playbook | n/a | misled twice, retired, next incident correct |

Approximate model cost for the whole run: A about $0.04, C about $0.01 (87% of A's input tokens were prompt-cache reads).

What this does and doesn't show:

- **Same accuracy, far less work.** Claude Haiku 5.5 solves this benchmark from scratch, so memory can't raise accuracy here; what it buys is the same answer without calling the model at all whenever an earlier incident applies.
- **Checking memory has a cost, and we report it.** On cold and novel incidents, graph memory takes more steps (recalled playbooks are checked before they are ruled out), though it still made fewer model calls on them (C 51 in total vs A 198).
- **Synthetic benchmark only.** 15-node company, three failure families, results describe this benchmark and nothing more. Arm B (text retrieval over the same memories) lands next; the numbers are frozen once all three arms run.

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

The acceptance test (seven checks, real process kill, full restart):

```bash
make acceptance-1      # resets company_a, runs s01, learns a playbook
docker compose down && docker compose up -d falkordb
make acceptance-2      # s04 after the restart, SIGKILL mid-investigation, takeover
```

The benchmark:

```bash
make eval-rules   # deterministic planner, no model calls, a few seconds
make eval         # the configured model; results in eval/results/<timestamp>/
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
| `sim/` | Synthetic company, incident simulator, org changes |
| `eval/` | Benchmark definition, truth files, oracle, runner, results |
| `scripts/` | Schema, seed, runners, acceptance test, persistence check |
| `tests/` | Offline tests and live tests against FalkorDB |
| `docs/` | The implementation plan |

## Still to come

Arm B (text retrieval via FalkorDB's vector index) and recall@5 · load and tenant-isolation benchmark · UI (Memory Lens, agent timeline, war-room chat, kill button) · final frozen numbers.

## AI assistance

AI coding assistants were used and are disclosed here, as the rules require. Draft, to be confirmed by the team before submission:

- **Claude (Anthropic)**: pair-programming on most of the code, tests and this README, live verification against FalkorDB, and review of the plan.
- **ChatGPT and Gemini**: independent reviews of the implementation plan (three rounds; their findings and our decisions are listed in `docs/Implementation-Plan.md`).
- **Claude Haiku 5.5** is also part of the product: it plans investigations and reads engineers' messages at runtime.

The design (graph model, memory algorithms, coordination protocol, benchmark) and every decision in the plan were made and verified by the team.
