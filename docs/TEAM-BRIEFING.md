# Team briefing: explain Blast Radius without notes

The rules say every member must be able to explain the graph model, the queries, the architecture and the technical decisions. This page is that walkthrough, with the real numbers from our own runs. Read it once, then try explaining each section aloud with the UI open.

## 1. The pitch (20 seconds)

"Blast Radius is a team of on-call agents that share one FalkorDB graph per company. When an incident is confirmed, its investigation becomes a playbook pinned to the failing node. Next time, the agents recall playbooks *near the alerting services in the dependency graph*, check them against live evidence before trusting them, and remember what each engineer asked for. It all survives restarts, and a worker can die mid-investigation without anything happening twice."

## 2. The architecture (who does what)

| Piece | What it is | Talks to |
|---|---|---|
| Simulator | Plays the outside world: breaks a node, produces metrics, logs and dependency health; publishes deploys to the graph. Knows the answer, never tells the agents. | FalkorDB (deploys only), the evidence tools |
| Triage | Deterministic: alerts become an `Incident` and an `investigate` task | FalkorDB |
| Investigator | Claims the task, recalls playbooks, checks them, otherwise plans with Claude Haiku 5.5 (rule-based fallback). Separate OS process. | FalkorDB, tools |
| Responder | Pages the right person their way, talks in the war room, records the verdict | FalkorDB, the engineer |
| Learner | Verdicts per memory, trust, new or extended playbooks | FalkorDB |

**The agents share nothing but FalkorDB.** No queue, no shared memory, no RPC. Task nodes are the queue; checkpoints are the progress log; actions are the pager.

## 3. The graph model (point at the diagram in the README)

Five layers in one graph per company:

- **World:** `Service`/`Datastore` with `DEPENDS_ON`; `Team`, `Person`, `OWNED_BY`, `ON_CALL` (with `valid_from`/`valid_to`); `Change` nodes for deploys (`Person -AUTHORED-> Change -MODIFIED-> Service`).
- **Incidents:** `Alert -PART_OF-> Incident`; the immutable `Decision`; `Feedback` on it.
- **Coordination:** `Task` (status, epoch, lease), `Checkpoint` per step, `Action` per intent.
- **Memory:** `Memory:Playbook` (procedural) and `Memory:Fact` (semantic), pinned with `ABOUT`, sourced with `LEARNED_FROM`, versioned with `SUPERSEDES`.
- **Conversation:** `Session -WITH-> Person`, `Session -CONCERNS-> Incident`, `Message -IN-> Session`.

**The edge that ties it together:** `Decision -USED-> Memory`, with the score, path, trust at use, every check's result, and later the verdict and trust after. That's what the Memory Lens reads. "What did the agent believe, and why?" is one query.

**Why a graph, in one sentence:** "Which past lesson applies to these alerts?" is a question about *what depends on what*, so we answer it by walking `DEPENDS_ON`, not by comparing text.

## 4. A1: recall by graph (the core query)

`memory/queries/recall.cypher`:

```cypher
MATCH (a:Service) WHERE a.name IN $alerting
MATCH p = (a)-[:DEPENDS_ON*1..2]->(n)
MATCH (n)<-[:ABOUT]-(m:Memory)
WHERE m.status = 'active' AND m.recorded_at <= $scenario_now
  AND m.valid_from <= $scenario_now
  AND (m.valid_to IS NULL OR $scenario_now < m.valid_to)
RETURN m.id, a.name, n.name, length(p) AS hops, [x IN nodes(p) | x.name] AS path, ...
```

- **Downstream only:** an alerting service fails because something it *depends on* failed. Walking both ways would pull in memory from unrelated services through hubs like `web-gateway`.
- **`recorded_at <= $scenario_now`:** a replayed incident can never see memory learned after it (no leakage from the future).
- **A1b** (`recall_kind.cypher`): playbooks learned on another datastore of the same kind, at half weight. That's how a lesson from `postgres-orders` helps `postgres-payments`.

**Score, computed in Python:** trust × e^(−age/30 days) × kind weight × Σ over alerting services of 0.5^hops.

Worked example from s04 (alerts on checkout-api, payments-gw, web-gateway; playbook learned in s01, trust 0.5, 8 hours old):
- Pinned copy on `postgres-orders`: checkout-api and web-gateway each reach it in 2 hops → 0.5 × 1 × (0.25 + 0.25) × 0.99 = **0.247**.
- Kind match on `postgres-payments`: payments-gw in 1 hop, checkout-api in 2 → 0.5 × 0.5 × (0.5 + 0.25) × 0.99 = **0.185**.

Both are checked. The first fails (`check_dependency_health(cart-svc)` says postgres-orders is healthy); the second passes all three checks. That is the Memory Lens on s04 (the *check* step under *What happened*, and the checking card on the graph).

## 5. Checking before trusting (A4 playbooks)

A playbook (`memory/templates.py`) is: **preconditions** (rule-outs, e.g. "no deploy on the alerting service in 2 h", "the caller sees the target unhealthy"), **steps** with an expected observation ("`db_connections_pct >= 90`"), a **conclusion** (`$target`) and a **stop rule** (any check fails → not applicable). Parameters are bound from the recall path: `$alerting` is the first node, `$caller` the node before the target, `$target` the pinned or kind-matched datastore.

The checks run as plain tool calls, **no model involved**. That's why repeat incidents take 0 LLM requests and 0.02 s in arm C.

**Same symptom, different cause (s05):** checkout errors again, but a deploy happened. The DB playbook's first precondition, `deploys == 0`, observes 1 and fails. Verdict: *not applicable*, trust unchanged. The agent investigates and finds the bad deploy.

## 6. A2: trust from verdicts

After the engineer confirms or rejects, each `USED` edge gets exactly one verdict (`WHERE u.verdict IS NULL` makes retries harmless):

- **helped:** followed, and its conclusion was right
- **misled:** followed, and wrong
- **not applicable:** a check failed, so it wasn't followed; no change

trust = (helped + α) / (helped + misled + α + β), with prior α = β = 1 for agent-made playbooks (start at 0.5) and α = 2, β = 1 for human-approved facts. **Retire when misled ≥ 2 and trust < 0.5.**

M5 in the UI: the planted wrong playbook misleads once → 1/3 = **0.33**, twice → 1/4 = **0.25**, retired; the third cache failure is diagnosed correctly. A playbook with real successes would not retire that fast. That's deliberate, and it's in the README.

**The FalkorDB finding here:** our first version updated `helped` in one `SET` clause and computed `trust` from it in the next. FalkorDB evaluated the second `SET` against the old value, so trust lagged one verdict behind and retirement never fired. A `WITH u, m` between the clauses fixed it.

## 7. A3: facts change by supersession

Priya says "For DB saturation, don't ping me on Slack. Open a ticket and paste the raw slow-query lines."
1. The message is stored verbatim.
2. Claude (or the rule parser) extracts **conditional** facts: `preferred_channel = ticket` and `wants_detail = raw_logs`, both with `condition_family = db_saturation`.
3. They're saved at once as the *agent's reading* (agent prior), sourced `LEARNED_FROM` the exact message.
4. The responder reads them back: "Saved: for DB saturation, notify you by ticket… Correct?" When Priya says yes, a **human-approved version supersedes** the agent's reading: the old version gets `valid_to`, the new one links `SUPERSEDES` to it. Nothing is edited or deleted (Memory tab, struck-through rows).
5. Next DB incident, possibly after a full restart: `preferences_for.cypher` loads the facts valid at the incident's time for that family, and the responder cites the message: "Sent this way per your note in incident s01-…".

The condition is part of the lineage key, so "bad deploy → page me" sits beside "DB saturation → ticket" instead of replacing it.

## 8. Coordination: the fence (know this cold)

Every task write starts with the same guard:

```cypher
MATCH (t:Task {id: $task_id})
WHERE t.status = 'leased' AND t.epoch = $epoch
  AND t.lease_owner = $instance AND t.lease_until >= timestamp()
```

- **Claim** (`claim.cypher`) takes the oldest claimable task, sets the lease from the **database clock** (`timestamp()`), and increments `epoch`. A heartbeat extends the lease every 2 s (demo timing; 10 s in production).
- **Checkpoint** each tool call *before* the next one starts. The checkpoint id is task + step number, so a retry is a no-op.
- **Actions** are keyed by intent (`incident:<id>:initial-notification`), not by recipient, so a retry or a takeover never pages a second person.
- Every write returns **ok**, **already_done** or **lease_lost**. On lease_lost the worker stops at once.

**The kill, step by step** (what the video shows):
1. inv-2 holds the lease, epoch 1, and checkpoints steps 1–3.
2. SIGKILL. No cleanup runs; heartbeats stop.
3. 6 s later the lease has expired. inv-1's claim succeeds and sets epoch 2.
4. inv-1 reads the checkpoints, reuses steps 1–3, and runs step 4.
5. Even if inv-2 came back, its next write says epoch 1 ≠ 2: rejected. The bench does exactly this every 50 ms and still sends 0 duplicates.

**Two clocks:** database time for leases (a worker's own clock can't be trusted across a long LLM call); scenario time for evidence, validity and `recorded_at` (so replays are reproducible).

## 9. Tenants

One graph per company (`company_a`, `company_b`), chosen from trusted config, **never by the model**. No tool takes a graph argument, and the MCP schema rejects one. Both companies have the same service names, keys and incident ids, but different people and a canary value. The isolation check searches every stored string, and every UI API response, for the other company's canary and names: 0 found.

## 10. Results in one breath

"Same model, same tools; only retrieval differs. All three arms got 30/30 (B 29/30), because Haiku can solve this benchmark from scratch. But graph memory needed 55 model requests against 192 with no memory and 107 with text memory, solved 20 of 30 incidents with no model call at all, and found the right memory in its top 5 every time, against 55% for text. An earlier run gave nearly the same numbers. Zero misleading uses, zero duplicate pages, and a planted wrong playbook retired after two."

Say the caveats before they're asked: synthetic benchmark; no accuracy gain because the model hits the ceiling; checks cost extra steps on novel incidents; the text arm uses a hashed bag of words.

## 11. Questions judges will ask

| Question | Answer |
|---|---|
| Why not a vector store? | Arm B *is* one, given the same memories, checks and learning. Text similarity found the right memory 55% of the time, graph proximity 100%, because "what's failing near these alerts" is a topology question. |
| How do you stop memory from making things worse? | Nothing recalled is trusted until its preconditions hold against live evidence; a wrong one gets *misled* and loses trust; a bad playbook retires after two misleading uses. 0 misleading uses in the benchmark. |
| What happens when a worker dies? | Fenced leases, synchronous checkpoints and intent-keyed actions: the next worker continues from the last checkpoint, and the dead one can't write even if it comes back. Shown live with a real SIGKILL. |
| How is tenant data kept apart? | A graph per company from trusted config; no tool takes a graph argument; canary tests over stored data and the UI API. |
| Where does FalkorDB do real work? | Recall is a variable-length `DEPENDS_ON` walk; who-to-page is a time-valid two-hop query; blast radius is up to four hops; coordination relies on single-query atomicity and `timestamp()`; every panel is a Cypher query (Cypher button). |
| Would it still work without FalkorDB? | No. The UI refuses to start without it, agents pause while it is down, and memory, coordination and conversation history are only in the graph. The Python graph double in `tests/` exists so offline tests can check every query's parameters and columns; product code never imports it (a test enforces that). |
| What did you learn about FalkorDB? | Three findings with reproductions in `docs/FALKORDB-FINDINGS.md`: the AOF replay crash on 4.22.1, triple-written constraints, and `SET`-clause visibility. |
| Is the data real? | Synthetic and seeded, so every number is reproducible with one command. Ground truth sits only in `eval/truth/`, and a test fails if agent code imports it. |
| Did you use AI tools? | Yes, as allowed and disclosed in the README: Claude for pair-programming and verification, ChatGPT and Gemini for plan reviews. Be specific and honest about who did what, and show you understand it by walking through any query or file they point at. |
| Why Claude Haiku? | Cheap, fast, and good enough to solve the benchmark from scratch, which makes the comparison about memory, not model skill. Every arm uses the same model. |
| What would you do next? | A harder benchmark where the model fails without memory; a neural embedder for arm B; Librarian consolidation of similar playbooks; live deployment on FalkorDB Cloud. |

## 12. Practice drill

1. Open the UI, click **s01**, and explain each timeline row as it appears.
2. In mission control, click **{ } query** on the graph card, open *recall: walk downstream from the alerts*, and read `recall.cypher` aloud (section 4).
3. Arm the kill, click **s04**, and narrate section 8 while it happens.
4. Click **s05** and explain the failed precondition (section 5).
5. Plant the wrong playbook, break `redis-cache` three times, and explain the trust numbers (section 6).

## 13. What changed on Oct 18 (audit fixes): know these too

An audit of the repo, with Claude Code, led to the changes in pull request #1. Rule 12 means each of you must be able to explain them, so here they are in plain words.

| Change | What to say | Where |
|---|---|---|
| **"No" really means no** | The agent's reading of Priya's message is saved at once, but if she doesn't say a plain yes, that reading is **closed** (`valid_to`), never deleted, and the agent says "Not saved." An unconfirmed reading never overrides a preference she approved. The rule parser now understands "do not paste raw logs, just a summary" and curly apostrophes. | `agents/responder.py`, `memory/queries/fact_retract.cypher`, `chat/preferences.py` |
| **Trust is summed per memory** | One decision can use the same playbook twice (pinned on postgres-orders, and by kind on postgres-payments). The trust query now sums the verdicts per memory before writing. Row by row, FalkorDB's SET visibility (our finding #3) could drop a "helped". | `memory/queries/feedback.cypher` |
| **A stale worker stops** | The responder checks its lease before the review and before war-room writes. If a send comes back `already_done`, it checks it still owns the task; if not, it stops. | `agents/responder.py` |
| **Graph algorithms as tools (Track 01)** | `rank_suspects` breaks ties with **FalkorDB `algo.pageRank`** over `DEPENDS_ON`: shared dependencies score higher. `explain_path` uses **`algo.SPpaths`** for the shortest path from the alerts to a node; the Memory Lens shows it for kind-transferred playbooks. Both are served over MCP (nine tools), but the benchmark's investigator keeps its seven, so the frozen results stay comparable. | `tools/queries/rank_suspects.cypher`, `explain_path.cypher` |
| **Honest eval numbers** | Each arm holds 3 playbooks, so "top 5" is a small pool. Graph recall has the right one **first 29%**, top-3 62%, top-5 100%; text: 10% / 29% / 48% (deterministic run). The 71% saving comes almost entirely from the 20 incidents where a memory applied; on cold ones graph memory makes fewer model calls but more tool calls. The simulator's evidence is clean, so this benchmark measures cost, not diagnostic ability. | README "Results", `eval/results/2026-10-18-rule-based-ranked/` |
| **When steps are capped** | `--max-steps 8`: no memory 30/30, graph 14/30. Checking memories that don't apply pushes cold incidents over budget, and a failed incident teaches nothing. Next fix: batch the checks, and learn from the engineer when the agent fails. | README "Limits" |
| **Duplicates that could fail** | The bench now counts duplicate sends the intent key absorbed, not only Action nodes (which `MERGE` caps at one). With a lease expired every 5 ms (7,690 times in 2 minutes): 0 duplicates. | `bench/load.py`, `bench/results/load-2026-10-18*.json` |
| **Live, read-only demo** | `PUBLIC_MODE=1`: every POST refused, the story plays itself (s01 → s04 with a real kill → s05), model off, graph reset on start. Locally, POSTs from other sites are refused and only `ALLOWED_HOSTS` are answered. | `docs/DEPLOY.md`, `web/app.py` |
| **Runs on Windows** | Kill uses `Popen.kill()` (Windows has no SIGKILL); the test double uses POSIX paths; files are read as UTF-8. | `web/supervisor.py`, `tests/graph_double.py` |

New judge questions:

| Question | Answer |
|---|---|
| "What if the engineer says no to the read-back?" | "The agent's reading is closed with `valid_to`, kept as history, and the next incident uses the default. Try it." |
| "Your recall@5 is 100%, but out of how many?" | "About 5 candidates from 3 playbooks. Ranked, graph recall is first 29% of the time and top-3 62%; text is 10% and 29%. Every candidate is checked, which is why nothing misled." |
| "Can memory make you slower?" | "On cold incidents, yes: about 2 more tool calls, though fewer model calls. Capped at 8 steps, that costs accuracy (14/30 vs 30/30). We measured it and wrote it down; batching the checks is next." |
| "Where are FalkorDB's graph algorithms?" | "`algo.pageRank` ranks suspects, `algo.SPpaths` explains paths; both are tools over MCP and in the UI's query drawer." |
