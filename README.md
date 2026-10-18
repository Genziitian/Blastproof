# Blast Radius

**Vector memory remembers what was said. Blast Radius remembers where it broke.**

On-call agents that turn every confirmed fix into a playbook pinned to the failing service in a FalkorDB dependency graph. On the next outage they find it by walking the graph, check it against live evidence before trusting it, and coordinate through leased tasks in the same graph, so a crashed worker is just a handover. Built by team **Blastproof** (sri ram, Aditi Akansha) for Graph Hacks 2026 on FalkorDB.

**▶ Demo video:** on YouTube (link added when uploaded) · **[Write-up with an interactive replay](https://genziitian.github.io/Blastproof/blog/)** (no install) · **[Run it](#run-it)** in five commands, no API key needed · **Tracks:** Agent Memory and Coordination (primary), Agents That Act on Connected Data

### Results in three numbers

- **71% fewer model calls.** Graph memory needed 55 LLM requests across the 30-incident benchmark; no memory needed 192. Both got all 30 diagnoses right ([frozen run](eval/results/2026-10-16T14-24-13Z-claude-haiku-5-5/summary.md)).
- **The right lesson, found by topology.** Graph recall had it in the top 5 for all 20 incidents where one existed; text similarity over the same memories, for 11 of 20.
- **Nothing done twice.** A worker SIGKILLed mid-investigation is taken over at the next step, not from scratch, and exactly one page goes out. A deliberately wrong playbook retired itself after misleading twice.

These come from a synthetic company (15 nodes, three failure families) in which the model already solves every incident from scratch, so here memory buys **cost, not accuracy**. The caveats are spelled out in [Results](#results) and [Limits](#limits-and-what-didnt-work).

![Mission control during the takeover: inv-2 was killed after step 3, inv-1 took over at step 4 under epoch 2, and the playbook learned from an earlier incident was recalled one hop from the alerts and is being checked against live evidence](docs/img/ui-takeover.png)

*Mission control, live (deterministic planner, demo timing): inv-2 was killed after step 3 and inv-1 took over at step 4. The playbook learned on `postgres-orders` was recalled for `postgres-payments` (one hop, same kind of datastore) and is being checked against live evidence. Every element is read from FalkorDB.*

### The problem

- Every incident is investigated from scratch. What the team learned last time sits in postmortems no agent reads.
- Old memory can be wrong for the new incident, and an agent that trusts it blindly makes things worse.
- When an agent crashes mid-investigation, the work is lost or the engineer is paged twice.

### Why a graph

"Which past lesson applies to these alerts?" is a question about what depends on what, not about wording. In the demo, the first outage alerts with *"p95 latency above SLO"* and the second with *"slow responses breaching SLO"*: different words, and a different database. Text similarity has little to go on. The graph does: `payments-gw` is one hop from `postgres-payments`, a datastore of the same kind as `postgres-orders`, where the playbook was learned. Recall is a walk downstream from the alerting services ([`recall.cypher`](memory/queries/recall.cypher), plus same-kind datastores in [`recall_kind.cypher`](memory/queries/recall_kind.cypher)):

```cypher
MATCH (a:Service) WHERE a.name IN $alerting
MATCH p = (a)-[:DEPENDS_ON*1..2]->(n)
MATCH (n)<-[:ABOUT]-(m:Memory)
WHERE m.status = 'active' AND m.recorded_at <= $scenario_now
RETURN m.id, n.name AS target, length(p) AS hops, [x IN nodes(p) | x.name] AS path
```

### How it works

```mermaid
flowchart LR
  A["1 · Alerts fire<br/>triage opens an incident and a task"] --> B["2 · Recall by graph<br/>playbooks pinned downstream of the alerts"]
  B --> C["3 · Check evidence<br/>preconditions vs live metrics, logs, deploys"]
  C -->|"holds: diagnosis"| E
  C -->|"fails: rule it out"| D["4 · Investigate<br/>LLM planner, every step checkpointed and fenced"]
  D --> E["5 · Engineer confirms<br/>war room; preferences read back"]
  E --> F["6 · Learn<br/>verdict per memory, trust, new or extended playbook"]
  F ==>|"next incident, even after a restart"| B
```

**Words used below:** a *playbook* is a learned memory: checks to run and the conclusion they support. A *verdict* says whether a memory helped, misled or didn't apply; trust moves with verdicts. A *lease* is a time-limited claim on a task; the *epoch* is a counter bumped on every claim, so a dead worker's late writes are rejected (*fencing*). A *checkpoint* is one saved tool call.

**FalkorDB is the only store:** the company graph, incidents, the agents' memory, the tasks they coordinate through, the war-room history and the evidence trail. Take it out and nothing works: the UI refuses to start without it, and the agents pause until it is back.

```bash
docker compose up -d falkordb && pip install -r requirements.txt && cp .env.example .env
python -m scripts.setup_schema && python -m scripts.seed
TIMING_PROFILE=demo python -m web.app --company a      # http://localhost:8000
```

**Read the write-up:** [Teaching on-call agents to remember](https://genziitian.github.io/Blastproof/blog/) (also served at `/blog/` by `make ui`; source in [`docs/blog/`](docs/blog/)), in English, Français, עברית, हिन्दी, Español or اردو.

## Contents

[The idea](#the-idea) · [Track 02](#track-02-what-it-asks-and-where-we-do-it) · [Results](#results) · [How memory works](#how-memory-works) · [Crash safety](#crash-safety-and-coordination) · [Graph data model](#graph-data-model) · [Queries](#queries) · [FalkorDB findings](#falkordb-findings) · [Run it](#run-it) · [Limits](#limits-and-what-didnt-work) · [AI assistance](#ai-assistance)

## The idea

When an incident is confirmed, its investigation becomes a **playbook** pinned to the failing node in the company's dependency graph: what to rule out first, what to expect, and where it came from. The next time alerts fire, agents recall the playbooks pinned **near the alerting services in the graph**, check each against live evidence before trusting it, and investigate from scratch only if none holds. Memory that misleads loses trust and retires. What engineers say in the war room ("for DB saturation, open a ticket with the raw lines") becomes a sourced, conditional preference that changes the next notification. All of it survives restarts, and a worker can die mid-investigation without anything being done twice.

## Track 02: what it asks and where we do it

> *"Build agents that remember across sessions and share state with each other. Memory should persist, update over time, and be available to every agent that needs it."*

| Focus point | Feature | Proof |
|---|---|---|
| Episodic, semantic, procedural memory | Incidents, checkpoints and immutable decisions; time-valid preference facts; playbooks with machine-checked preconditions | Benchmark ([Results](#results)), including the planted wrong playbook (M5); Memory Lens |
| Persistent conversation history | War room: verbatim messages per engineer and incident, read-back before saving, preferences cited later, earlier sessions shown | Acceptance test, check 6 (preference applied after a full restart); `tests/test_g2_live.py` |
| Shared state and handoffs | Fenced tasks in the graph: investigator → responder → learner, derived-id handoffs, intent-keyed actions | Acceptance test, checks 4–7, with a real SIGKILL; agent timeline |
| High-concurrency reads and writes | Two companies, every agent in its own claim loop, leases expired at random | `make bench`: 0 duplicate notifications |
| Separate memory per user or tenant | One graph per company; per-engineer preferences; no tool takes a graph argument | `make isolation`; the UI API test; canary search: 0 found |
| Persist, update over time | RDB snapshots + restart test; trust moves on verdicts; facts superseded, never edited; a wrong playbook retires | Acceptance part 1 → restart → part 2; M5 |

### Track 01: agents that act on connected data

- **Multi-hop graph queries as the agent's tools:** shared dependencies of the alerting services (1–3 hops), blast radius (up to 4 hops), who to page right now (a time-valid two-hop walk), and deploy history (`Person → Change → Service`). The investigator decides with them; the responder pages with them.
- **FalkorDB graph algorithms as tools:** `rank_suspects` orders where to look first by how many alerting services reach a node, how close it is, then **`algo.pageRank`** over `DEPENDS_ON` (how much of the system leans on it). `explain_path` gives **`algo.SPpaths`** shortest paths from the alerts to any node; the Memory Lens uses it to show how the alerts reach the node a playbook was learned on.
- **Tool selection through MCP:** all nine tools are served over MCP (below). The two algorithm tools are for people and other agents; the benchmark's investigator keeps its seven, so the frozen results stay comparable.
- **Explainable:** every decision stores what it recalled, why (path, hops, score), and each check's evidence for and against; every UI panel opens the Cypher behind it.

## Results

A 30-incident synthetic benchmark replayed in time order. Three setups, each in its own graph, with the same model (Claude Haiku 5.5), tools, step budget (12), oracle and learning; **only how memories are retrieved differs**:

- **A, no memory:** always investigates from scratch.
- **B, text memory:** tries the memories whose text is most similar to the alerts (embedding similarity, FalkorDB `vec.cosineDistance`).
- **C, graph memory:** tries the memories pinned near the alerting services in the dependency graph.

Frozen run on Oct 16 from the submitted code (`eval/results/2026-10-16T14-24-13Z-claude-haiku-5-5/`, uncached, 0 model failures):

| | A: no memory | B: text memory | C: graph memory |
|---|---|---|---|
| Root cause correct | 30/30 | 29/30 | **30/30** |
| LLM requests, whole benchmark | 192 | 107 (−44%) | **55 (−71%)** |
| Input / output tokens | 456k / 62k | 266k / 34k | **133k / 18k** |
| Wall-clock time, whole benchmark | 433 s | 241 s | **125 s** |
| Incidents solved with no model call | 0 | 10 | **20** |
| Repeat incidents: LLM requests, seconds each | 6.0, 13.3 s | 1.7, 3.6 s | **0, 0.02 s** |
| Related-service incidents: LLM requests, seconds each | 5.8, 12.4 s | 2.7, 5.7 s | **0, 0.02 s** |
| Same symptom, different cause: LLM requests, seconds each | 6.5, 15.0 s | 3.2, 7.7 s | **0.8, 1.7 s** |
| Recall@5 of a memory that gives the right answer (20 incidents where one exists, same snapshot) | n/a | 55% | **100%** |
| Times a memory misled the agent | n/a | 0 | 0 |
| Right person paged after an on-call or ownership change | 3/3 | 3/3 | 3/3 |
| Duplicate notifications | 0 | 0 | 0 |
| M5: a deliberately wrong playbook | n/a | n/a | misled twice, retired, next incident correct |

Approximate model cost for the whole benchmark: A $0.04, B $0.02, C $0.01 (most input tokens are prompt-cache reads). An earlier run on Oct 15, before the UI work, gave nearly the same picture: 185 / 101 / 52 model requests, 30 / 29 / 30 correct, recall@5 48% vs 100% (in `eval/results/` too).

What this does and doesn't show:

- **Same accuracy, far less work, and where the saving comes from.** Claude Haiku 5.5 already solves this benchmark from scratch, so memory can't raise accuracy here. Graph memory gives the same answers with 71% fewer model requests. Almost all of that is the 20 incidents where a learned playbook applied: 119 model requests with no memory, 0 with graph memory. On the other 10 (cold and novel), graph memory made 25% fewer requests (73 → 55) but 31% more tool calls (61 → 80), because it checks recalled playbooks before investigating. So the saving grows with how often incidents repeat; this benchmark has 20 repeats in 30.
- **Text memory finds the right memory about half as often.** When a memory that gives the right answer exists, text similarity ranks it in the top 5 for 55% of incidents (48% in the earlier run), graph proximity for 100%: "which node is failing near these alerts" is a question about the dependency graph, not about wording. Read that as top 5 of a small pool: each arm only ever holds 3 playbooks, and recall returns about 5 (playbook, target) pairs. Ranked, on the same snapshot ([deterministic run, Oct 18](eval/results/2026-10-18-rule-based-ranked/summary.md)), graph recall puts the right one first 29% of the time and in the top 3 62% of the time; text recall 10% and 29%. Graph recall is never misled because every candidate is checked, not because it always ranks the right one first.
- **Checking the wrong memories has a cost.** Every recalled memory is checked against live evidence before it is trusted, so no arm was ever misled; but checks take steps. Arm B lost one incident (e20, in both runs) this way: it checked five wrong memories, and the model ran out of the 12-step budget. On cold and novel incidents, graph memory also takes more steps than no memory (about 8 vs 6), though fewer model calls.
- **Caveat on B:** text is embedded with a deterministic hashed bag of words; a neural embedder (`EMBED_MODEL`) is supported and would be a fairer opponent.
- **Synthetic benchmark, easy evidence.** A 15-node company and three failure families; the results describe this benchmark and nothing more. In this simulator the evidence is clean: caller logs name the failing dependency, the dependency-health check marks exactly the failing node, and there is never an innocent deploy in the window. That is why a rule-based planner with no model and no memory also gets 30/30 ([deterministic run, all three arms](eval/results/2026-10-18-rule-based-ranked/summary.md); repeat/related steps A 6.2/5.3, B 6.3/7.5, C 3.0/4.8). So this benchmark measures the **cost** of diagnosis, not diagnostic ability, and "0 misleading uses" means the checks worked on clean evidence. A split with noisy evidence is the next experiment.

### Concurrency and tenant isolation (M8, M9)

Two companies, every agent in its own claim loop, 20 incidents fired at once, FalkorDB in Docker on one laptop, deterministic planner (this measures FalkorDB and the coordination protocol, not a model). `make bench`, `make isolation`.

| Worker pairs per company | Stalled workers | Done | Incidents / min | Memory reads p50 / p95 | Memory writes p50 / p95 | Duplicate notifications | Takeovers |
|---|---|---|---|---|---|---|---|
| 1 | none | 20/20 | 6,633 | 0.35 / 0.81 ms | 0.33 / 1.01 ms | 0 | 0 |
| 2 | none | 20/20 | 9,185 | 0.61 / 1.54 ms | 0.63 / 1.82 ms | 0 | 0 |
| 4 | none | 20/20 | 9,062 | 0.87 / 2.00 ms | 1.22 / 3.20 ms | 0 | 0 |
| 4 | a held lease expired every 50 ms | 20/20 | 8,712 | 0.71 / 1.86 ms | 0.91 / 2.58 ms | **0** | 1 |

One run on Oct 16 (`bench/results/load.json`), FalkorDB 4.22.1 with RDB snapshots on a MacBook Air. Throughput levels off beyond 2 pairs: FalkorDB runs one graph's writes one at a time, and every agent step is a short write. Earlier runs with the append-only file (fsync every second) were about 3× slower (≈2,000–3,100 incidents/min, p50 ≈2–3 ms), with the same zero duplicates. With stalled workers, another worker takes the task over and the stalled one's next write is rejected by the fence (here 1 takeover; at this speed most incidents finish between chaos ticks, and slower runs saw 6–7). Nothing is ever sent twice.

**Can "0 duplicates" fail?** Not as a count of Action nodes alone, since the intent key caps it at one per incident. So the benchmark now also counts the attempts to notify again that the intent key absorbed (`duplicate_sends_absorbed`): the mechanism doing its job, not just its result. A rerun on Oct 18 (Windows 11 desktop, same FalkorDB image; [`load-2026-10-18.json`](bench/results/load-2026-10-18.json)) gave 0 duplicate notifications and 2 absorbed re-sends with 3 takeovers in the stalled-worker row. A harsher run that expired a held lease every 5 ms (7,690 expiries in 2 minutes; [`load-2026-10-18-chaos-5ms.json`](bench/results/load-2026-10-18-chaos-5ms.json)) still sent nothing twice: 2 takeovers, 0 duplicates. Two tasks hit the 3-attempt limit and wait for a human (`stuck`), as designed, so 18 of 20 incidents finished.

Isolation: identical service names, keys and incident ids in both companies; every stored string in each graph, and every UI API response, is searched for the other company's canary and people: 0 found.

## How memory works

1. **Triage** turns alerts into an `Incident` and an `investigate` task.
2. **Investigator** recalls playbooks pinned near the alerting services (A1, A1b) and records what it recalled before checking anything. It checks each against live evidence without the model; the first whose preconditions and expected observations all hold is the diagnosis. Otherwise it investigates with the LLM planner, guard-railed by a rule-based planner. Every tool call is checkpointed before the next one.
3. **Responder** notifies whoever owns the failing node and is on call *at the incident's time*, the way that person asked for this kind of incident, citing the message where they asked. What the engineer says is stored verbatim; instructions become approved preferences only after a read-back and a yes.
4. **Learner** gives each memory used a verdict, updates trust, retires memories that keep misleading, and turns a confirmed investigation into a sourced playbook, or adds the new incident as a source of an existing one.

The `Decision` and its `USED` edges record every memory considered, with the evidence for and against, so "what did the agent believe then, and why?" is a query, not a guess. That is what the Memory Lens shows:

![Same symptoms, different cause (s05): the DB playbook was recalled twice (pinned, and by kind); the card on the graph shows the first copy ruled out because checkout-api had a deploy, and the Memory Lens on the left shows the failed check and observed value; trust unchanged](docs/img/ui-lens-ruled-out.png)

| | Algorithm | Where |
|---|---|---|
| A1 | **Graph recall, downstream only, with paths.** Playbooks `ABOUT` a node 0–2 `DEPENDS_ON` hops downstream of an alerting service. Score = trust × e^(−age / 30 days) × Σ over alerting services of 0.5^hops; top 5 with their paths. | `memory/queries/recall*.cypher`, `memory/recall.py` |
| A1b | **Kind transfer.** Playbooks learned on another datastore of the same kind (any `postgres`), at half weight. | `memory/queries/recall_kind.cypher` |
| A2 | **Trust from per-memory verdicts:** helped (followed and right), misled (followed and wrong), not applicable (a precondition failed; no change). trust = (helped + α) / (helped + misled + α + β), agent prior 1/1, human prior 2/1. Retire when misled ≥ 2 and trust < 0.5. | `memory/queries/feedback.cypher` |
| A3 | **Facts change by supersession, never by edit.** Validate first, then create one new version that closes the old one's `valid_to`; conditional lineage, so "DB saturation → ticket" and "bad deploy → page" coexist. | `memory/queries/fact_*.cypher` |
| A4 | **Candidate playbook from a confirmed run:** the rule-outs that held and the observation that confirmed the cause, parameterised (`$alerting`, `$caller`, `$target`), machine-checkable, with a stop rule. | `memory/templates.py`, `memory/queries/write_playbook.cypher` |
| Org | On-call and ownership changes close the old edge and open a new one, so `who_to_page` is right for any moment. | `sim/queries/` |

## Crash safety and coordination

FalkorDB makes each query atomic; the agents add three rules on top:

- **Fence every task write.** Claims start a new epoch using the database clock; every write checks status, epoch, owner and `lease_until >= timestamp()`, and returns `ok`, `already_done` or `lease_lost`. A worker that lost its lease stops at once.
- **Checkpoint synchronously.** Each tool call is written before the next starts. A replacement worker reads the checkpoints and continues at step n + 1.
- **Key every action by intent.** `incident:<id>:initial-notification` is sent once, whoever sends it; the recipient is fixed at the first write.

Plus derived-id handoffs, an attempts limit and a stuck sweep. The acceptance test SIGKILLs a real worker process after checkpoint 3, after a full `docker compose down && up`; the replacement resumes at step 4 under epoch 2, and exactly one notification goes out.

## Graph data model

One graph per company (`company_a`, `company_b`), identical in shape. Read off a populated graph:

```mermaid
flowchart LR
  subgraph World
    Service -->|DEPENDS_ON| Service
    Service -->|DEPENDS_ON| Datastore
    Service -->|OWNED_BY| Team
    Datastore -->|OWNED_BY| Team
    Person -->|MEMBER_OF| Team
    Person -->|ON_CALL| Team
    Person -->|AUTHORED| Change -->|MODIFIED| Service
  end
  subgraph Incidents
    Alert -->|FIRED_ON| Service
    Alert -->|PART_OF| Incident
    Incident -->|TOUCHED role| Datastore
    Decision -->|FOR| Incident
    Feedback -->|ON| Decision
  end
  subgraph Coordination
    Task -->|FOR| Incident
    Task -->|HAS_CHECKPOINT| Checkpoint
    Task -->|NEXT| Task
    Task -->|EMITTED| Action
  end
  subgraph Conversation
    Session -->|WITH| Person
    Session -->|CONCERNS| Incident
    Message -->|IN| Session
  end
  subgraph Memory
    Playbook["Memory:Playbook"] -->|ABOUT| Datastore
    Playbook -->|LEARNED_FROM| Incident
    Fact["Memory:Fact"] -->|ABOUT| Person
    Fact -->|LEARNED_FROM| Message
    Fact -->|SUPERSEDES| Fact
    Decision -->|USED| Playbook
  end
```

**Nodes**

| Label | Layer | Key properties |
|---|---|---|
| `Service`, `Datastore` | World | `key`, `name`, `tier`, `customer_facing`; datastores `kind` (postgres, redis, kafka) |
| `Team`, `Person` | World | `key`, `name`, `channel`; `handle` |
| `Change` | World | `key`, `kind` (deploy, config), `at`, `summary` |
| `Alert` | Incident | `key`, `signal`, `text`, `fired_at` |
| `Incident` | Episodic | `key`, `id`, `status`, `observed_at`, `opened_at`, `resolved_at`, `signature` (family + root kind, set on confirm) |
| `Decision` | Audit, immutable | `id`, `kind`, `root`, `family`, `summary`, `evidence_steps`, `agent`, `task_id`, `epoch` |
| `Feedback` | Incident | `id` (stable), `verdict`, `by`, `at` |
| `Memory:Playbook` | Procedural | `signature`, `family`, `applies_to_kind`, `params_json`, `preconditions_json`, `steps_json`, `conclusion`, `stop_if`, `payload_hash` + shared memory fields |
| `Memory:Fact` | Semantic | `subject`, `predicate`, `condition_family`, `object`, `approved_by` + shared memory fields |
| `Session`, `Message` | Conversation | `id`, `started_at`; `key`, `role`, `text`, `seq`, `at` |
| `Task` | Coordination | `id`, `type`, `status`, `epoch`, `attempts`, `lease_owner`, `lease_until`, `claimed_by[]`, `claimed_at[]`, `recalled_json` |
| `Checkpoint` | Coordination | `cid` (task + n), `n`, `epoch`, `agent`, `tool`, `args_json`, `observation`, `at`, `scenario_at` |
| `Action` | Coordination | `key` (intent), `kind`, `recipient`, `channel`, `payload`, `status`, `sent_at` |
| `Canary` | Isolation test | `value` (per company) |

Shared memory fields: `id`, `lineage_id`, `version`, `source` (agent or human), `valid_from`, `valid_to` (absent means open-ended), `recorded_at`, `status` (active, retired), `helped`, `misled`, `prior_a`, `prior_b`, `trust`. FalkorDB can't store maps, so nested playbook parts are validated JSON strings.

**Edges**

| Type | From → to | Properties |
|---|---|---|
| `DEPENDS_ON` | Service → Service, Datastore | |
| `OWNED_BY`, `ON_CALL`, `MEMBER_OF` | Service/Datastore → Team; Person → Team | `valid_from`, `valid_to`: closed and reopened, never edited |
| `AUTHORED`, `MODIFIED` | Person → Change → Service | deploy history |
| `FIRED_ON`, `PART_OF` | Alert → Service; Alert → Incident | |
| `TOUCHED` | Incident → Service, Datastore | `role`: alerting, root |
| `FOR` | Task, Decision → Incident | |
| `HAS_CHECKPOINT`, `NEXT`, `EMITTED` | Task → Checkpoint, Task, Action | |
| `ABOUT` | Memory → Service, Datastore, Person | where a memory applies |
| `LEARNED_FROM` | Memory → Incident, Message | provenance |
| `SUPERSEDES` | Fact → Fact | new version → old |
| `USED` | Decision → Memory | `target`, `score`, `hops`, `path`, `trust_at_use`, `applied`, `checks_json`, `verdict` (set once), `trust_after` |
| `ON` | Feedback → Decision | |
| `WITH`, `CONCERNS`, `IN` | Session → Person, Incident; Message → Session | |

**Indexes and constraints** (`make schema`): unique on `Memory.id`, `Task.id`, `Decision.id`, `Action.key`, `Feedback.id`, `Checkpoint.cid`, `Session.id`, `Message.key`, `Incident.key`, `Alert.key`, `Change.key` and the world nodes' `key`; plain indexes on `Service.name`, `Task.status`, `Task.type`, `Memory.lineage_id`, `Playbook.signature`, `Incident.status`. Constraints are polled until `OPERATIONAL` before any worker starts.

**Rules the code keeps:**
- **One graph per company**, chosen from trusted config, never by the model.
- **Two clocks:** `timestamp()` inside queries for leases; scenario time for evidence, validity and `recorded_at`, so a replayed incident never sees memory from its future.
- **Memory is never edited:** facts are superseded, playbooks gain sources, trust moves only on verdicts.
- **Ground truth lives only in `eval/truth/`.** `tests/test_boundaries.py` fails if agent-side code imports it.

## Queries

All 76 queries are `.cypher` files, indexed with what each does in **[`docs/QUERIES.md`](docs/QUERIES.md)** (generated from the files; a test keeps it current). In the UI, the **{ } query** button on each part opens the queries behind it. The ones the product depends on most:

| Query | Does |
|---|---|
| [`memory/queries/recall.cypher`](memory/queries/recall.cypher) | A1: playbooks 1–2 hops downstream of the alerting services, with paths |
| [`memory/queries/recall_kind.cypher`](memory/queries/recall_kind.cypher) | A1b: playbooks learned on another datastore of the same kind |
| [`memory/queries/feedback.cypher`](memory/queries/feedback.cypher) | A2: one verdict per `USED` edge, trust and retirement |
| [`memory/queries/fact_supersede.cypher`](memory/queries/fact_supersede.cypher) | A3: a new fact version that closes the old one |
| [`memory/queries/write_playbook.cypher`](memory/queries/write_playbook.cypher) | A4: a sourced candidate playbook |
| [`coord/queries/claim.cypher`](coord/queries/claim.cypher) | Claim the oldest claimable task, new fencing epoch, database clock |
| [`coord/queries/checkpoint.cypher`](coord/queries/checkpoint.cypher) | Fenced, idempotent checkpoint |
| [`coord/queries/send_action.cypher`](coord/queries/send_action.cypher) | Send once per intent, report `already_done` on retry |
| [`agents/queries/confirm.cypher`](agents/queries/confirm.cypher) | One write: feedback, resolve the incident, queue learning |
| [`chat/queries/preferences_for.cypher`](chat/queries/preferences_for.cypher) | Preferences in force at incident time, with the message they came from |
| [`tools/queries/who_to_page.cypher`](tools/queries/who_to_page.cypher) | Owner and on-call *at scenario time* |
| [`tools/queries/upstream_candidates.cypher`](tools/queries/upstream_candidates.cypher) | Shared downstream dependencies of the alerting services |
| [`tools/queries/rank_suspects.cypher`](tools/queries/rank_suspects.cypher) | The same walk, ties broken by FalkorDB `algo.pageRank` over `DEPENDS_ON` |
| [`tools/queries/explain_path.cypher`](tools/queries/explain_path.cypher) | FalkorDB `algo.SPpaths`: the shortest path from the alerts to a node |
| [`memory/queries/fact_retract.cypher`](memory/queries/fact_retract.cypher) | Close an agent's reading the engineer didn't confirm |

## FalkorDB findings

Details and reproductions in [`docs/FALKORDB-FINDINGS.md`](docs/FALKORDB-FINDINGS.md):

- **AOF replay diverged on 4.22.1** after a day of graph deletes and re-creates (`GRAPH.EFFECT references label/relationship-type 'Memory' (id 0) which doesn't match local schema state`), and the server shut itself down on every start. We persist with RDB snapshots instead; the restart test passes.
- **Each unique-constraint creation is written to the AOF three times** (28 commands, 84 entries), and replay logs `Constraint already exists` errors (4.18.3).
- **A later `SET` clause reads the values from before an earlier `SET` clause** (`SET m.h = m.h + 1 SET m.t = m.h` leaves `t` at the old `h`); a `WITH` between them fixes it. This silently broke our trust update until a FalkorDB run caught it.

## Run it

Requires Docker and Python 3.10+. Run everything from this folder. Tested on macOS and on Windows 11; on Linux the same commands apply.

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env     # settings are read from .env automatically

make db          # FalkorDB 4.22.1, pinned by digest (Browser on http://localhost:3000)
make schema      # indexes + unique constraints; waits until all are OPERATIONAL
make seed        # explicit; nothing reseeds on startup
make ui          # http://localhost:8000 (landing page), /mission-control (the live demo), /blog/ (the write-up)
```

![The landing page: the idea, told with a replay of a real incident read from the graph](docs/img/landing.png)

**A public, read-only copy** runs in one container beside FalkorDB: `FALKORDB_PASSWORD=... docker compose -f docker-compose.public.yml up -d --build`, then http://localhost:8080. Every write is refused, and the story plays by itself, with a real kill and takeover every round. Details and platform notes are in [`docs/DEPLOY.md`](docs/DEPLOY.md).

If something else already listens on port 6379 (a local Redis), set `FALKORDB_PORT=6380` in `.env`; Docker Compose and the Python client both read it.

**On Windows** the `make` targets need Git Bash (or WSL). From PowerShell, the same steps are: `python -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, `copy .env.example .env`, `docker compose up -d falkordb`, `python -m scripts.setup_schema`, `python -m scripts.seed`, then `$env:TIMING_PROFILE='demo'; python -m web.app --company a`.

**The UI** has two pages. The **landing page** (`/`) explains the idea with live data: its hero replays a real incident from the graph, and every number, check and playbook on it is read from the API (a labelled recorded run stands in until this machine has run its own). **Mission control** (`/mission-control`) is the live demo: it runs two investigators as separate processes (Kill sends a real SIGKILL), plus the responder and learner, and reads everything back from FalkorDB. You play the on-call engineer in the war room, or switch on "scripted engineer" in Director. Each incident is told as the learning loop, step by step, every animation driven by a real event in the graph, and **← ▶ →** replays any incident from its stored steps. `/dark` and `/classic` keep the earlier views. Demo timing (6 s lease, 2 s heartbeat; production 30 s / 10 s) is labelled on screen. Panels and the demo walkthrough: [`web/README.md`](web/README.md).

**The acceptance test** (seven checks, real process kill, full restart):

```bash
make acceptance-1      # resets company_a, runs s01, learns a playbook
docker compose down && docker compose up -d falkordb
make acceptance-2      # s04 after the restart, SIGKILL mid-investigation, takeover
```

**Persistence:** FalkorDB writes an RDB snapshot every 30 s if anything changed and on every shutdown, into a named Docker volume. `make acceptance-2` and the UI wait until FalkorDB has finished loading after a restart. If FalkorDB goes away while the UI runs, the agents log one line and wait, and the page shows a banner until it's back.

**Benchmarks and tests:**

```bash
make test        # every suite on the in-memory graph double (offline)
make test-live   # the integration suites on FalkorDB too
make eval-rules  # arms A, B, C with the deterministic planner, no model calls
make eval        # arms A, B, C with the configured model; eval/results/<timestamp>/
make bench       # concurrency with 1, 2 and 4 worker pairs, then with stalled workers
make isolation   # tenant isolation
make story       # s01 -> s04 -> s05 in the terminal
```

The integration suites are written once and run on two backends: FalkorDB when it is reachable, and `tests/graph_double.py` always. The double runs each query's Python twin and checks every call against the real `.cypher` file (parameters, RETURN columns, property types). Only FalkorDB proves the Cypher itself, and it caught what the double could not (the `SET` finding above). The double lives in `tests/` and only tests use it: the UI, workers, eval, benchmark and acceptance test all connect to FalkorDB, and a test fails if product code imports anything from `tests/`.

**Model.** Everything runs without a model (rule-based planner and preference parser). With a model, the investigator plans with it and the war room reads the engineer's messages with it; any invalid answer falls back to the rule-based step.
- **Claude** (what the results use): `LLM_BASE_URL=https://api.anthropic.com`, `LLM_MODEL=claude-haiku-5-5`, `LLM_API_KEY=...`. Native Messages API with prompt caching: tools, instructions and earlier steps are re-read from cache on each turn.
- **Any OpenAI-compatible endpoint** (Gemini, DeepSeek, Groq, OpenAI, Ollama): set base URL, model and key; see `.env.example`.

**MCP.** `python -m tools.mcp_server --company a --scenario s01` serves nine tools to any MCP client: the investigator's seven (four multi-hop graph queries, three evidence tools) plus the two graph-algorithm tools, `rank_suspects` (PageRank) and `explain_path` (shortest paths). For Claude Desktop or Claude Code, add it as a stdio server with that command, run from this folder, and ask, for example, "who do I page if postgres-orders fails, and what else breaks?". `tests/test_mcp.py` runs a real client session against it.

### Layout

| Path | Contents |
| --- | --- |
| `agents/` | Worker loop, triage, planners, investigator, responder, learner |
| `memory/` | Recall, playbooks, templates, verdicts, fact writes, and their queries |
| `chat/` | War-room sessions, preference extraction, recap |
| `coord/` | Fenced task coordination and its queries |
| `tools/` | Tool registry, graph tools, MCP server |
| `sim/` | Synthetic company, incident simulator (in-process, or shared between processes via `sim/store.py`), deploy history, org changes |
| `eval/` | Benchmark definition, truth files, oracle, runner, results |
| `bench/` | Load benchmark with stalled workers, tenant-isolation check |
| `web/` | The UI: landing page and mission control, a JSON API, its read queries, the investigator supervisor, the public read-only mode |
| `scripts/` | Schema, seed, runners, acceptance test, persistence check, query index |
| `tests/` | Offline tests and live tests against FalkorDB |
| `docs/` | [Implementation plan](docs/Implementation-Plan.md), [FalkorDB findings](docs/FALKORDB-FINDINGS.md), [query index](docs/QUERIES.md), [team briefing](docs/TEAM-BRIEFING.md) (the system explained, with judge Q&A), [demo script](docs/DEMO-SCRIPT.md), screenshots |

## Limits and what didn't work

- **Synthetic world.** One 15-node company, three failure families, a simulator that produces evidence from a seed. Real incidents are messier; the benchmark describes itself only.
- **No accuracy gain to show.** The model already solves every benchmark incident from scratch, so memory's measured benefit is less work, not more correct answers. A harder benchmark or a smaller model would test accuracy.
- **Checking costs steps.** Ruling out recalled memories takes tool calls; on novel incidents graph memory takes more steps than no memory, and text memory once ran out of its step budget. When steps are capped this matters: with an 8-step budget (`python -m eval.run --rule-based --max-steps 8`, [results](eval/results/2026-10-18-rule-based-max-steps-8/summary.md)) no memory solves 30/30, graph memory 14/30 and text memory 12/30. Checks on cold incidents push them over the budget, and an unsolved incident teaches nothing, so later repeats fail too. Next: batch each playbook's first check into one evidence read, and learn from the engineer's diagnosis when the agent fails, so memory never costs more than it saves.
- **Kind transfer is datastore-only.** A playbook learned on one postgres helps another; a bad-deploy playbook spreads to another service only once a confirmed incident pins it there. We kept arms B and C symmetric rather than widen this.
- **Text arm uses a hashed bag of words** by default, a weak opponent for graph recall; a neural embedder is supported.
- **Workers are processes, not containers.** The UI starts and kills them. For a public demo the app and its workers are one container beside FalkorDB ([`docs/DEPLOY.md`](docs/DEPLOY.md)).
- **Persistence trades durability for safety:** RDB snapshots can lose up to 30 s of writes if FalkorDB itself crashes hard (a clean `docker compose down` loses nothing). We moved off AOF because of the 4.22.1 replay failure above.
- **Live deployment is read-only.** `PUBLIC_MODE=1` (Dockerfile, `docker-compose.public.yml`, [`docs/DEPLOY.md`](docs/DEPLOY.md)) refuses every write and plays the story by itself, with the model off. The full, interactive demo is local.
- **Pins carry no time.** A pin added to an existing playbook (a new `ABOUT` edge) has no timestamp, so a replay run out of time order could see a pin from its future. The benchmark replays in time order, so its results are unaffected.
- **What didn't work:**
  - *HNSW for text recall.* Early on it seemed to return too few neighbours on a tiny graph. We couldn't reproduce that in isolation, so it isn't reported as a bug, but arm B uses exact cosine distance.
  - *Gemini as the eval model.* Free-tier quota and model availability (404s and 503s) blocked full runs.
  - *Exact-argument playbook matching.* Extra optional arguments from the model (`window_min`) broke learning until we matched on a subset.

## AI assistance

AI coding assistants were used and are disclosed here, as the rules require:

- **Claude (Anthropic)**: pair-programming on most of the code, tests and this README, live verification against FalkorDB, and review of the plan.
- **ChatGPT and Gemini**: independent reviews of the implementation plan (three rounds; their findings and our decisions are listed in `docs/Implementation-Plan.md`).
- **Claude Code** (Claude Opus 5.5): on Oct 18, an audit of the repository (running it on Windows, the tests, a step-budget experiment, a review of the evaluation) and the fixes that followed: cross-platform fixes, the war-room read-back fix, the evaluation disclosures, the graph-algorithm tools, and UI and web hardening. They came in as one pull request for the team to review.
- **Claude Haiku 5.5** is also part of the product: it plans investigations and reads engineers' messages at runtime.

The design (graph model, memory algorithms, coordination protocol, benchmark) and every decision in the plan were made and verified by the team.
