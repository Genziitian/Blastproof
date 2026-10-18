# Submission: answers to paste, in the form's order

Form: https://www.wemakedevs.org/hackathons/falkordb/submit (editable until the deadline).
Deadline: **Sun Oct 18, 11:59 PM IST**; target 8 PM. Team **Blastproof**: sri ram (@sriramdevs, leader), Aditi Akansha (@astral0911). The team can't change after submitting, so invite anyone else who worked on it first.

## Part 1: Project details

### Project title

Blast Radius

### Description (what problem does it solve, and who is it for?)

Blast Radius is a team of on-call AI agents that remember previous incidents and coordinate through one FalkorDB graph per company. It is for SRE and on-call teams who want agents to help with outages without repeating work or paging people twice.

The problem: every incident gets investigated from scratch. What the team learned last time sits in postmortems no agent reads, and text search misses a related outage when the alerts are worded differently. Old memory can also be wrong for the new incident. And when an agent crashes mid-investigation, the work is lost or the engineer gets paged twice.

Blast Radius turns each confirmed investigation into a playbook pinned to the failing service. On the next incident, agents recall playbooks near the alerting services by walking the dependency graph, check each one against live evidence before trusting it, and lower trust in any that mislead. What engineers say in the war room becomes sourced preferences ("tickets with raw logs for database incidents"). A worker killed mid-investigation is taken over from its last checkpoint, and exactly one page goes out. Everything survives a full database restart.

On a 30-incident synthetic benchmark with Claude Haiku 5.5, graph memory needed 71% fewer model requests than no memory (55 vs 192), solved 20 incidents with no model call, and found the right memory every time, against 55% for text similarity. All data is synthetic; AI assistance is disclosed in the README.

### Tracks (select all that apply)

- [x] Agent Memory and Coordination (primary)
- [x] Agents That Act on Connected Data: the investigator acts through multi-hop graph tools (upstream candidates, blast radius, who to page, recent changes), also served over MCP.

Rule 5 allows entering any or all tracks as long as each is named. Whether one project can win two prizes doesn't change whether to enter. Company Brain is left out on purpose: our company graph is there to serve incident response, not to be a general knowledge base.

### Repository

https://github.com/Genziitian/Blastproof

### Demo video

*(YouTube link, public or unlisted. Script: `docs/DEMO-SCRIPT.md`.)*

### Live demo or deployment

Leave empty, or paste https://github.com/Genziitian/Blastproof#run-it (complete local setup: `make db schema seed ui`).

### How did you use FalkorDB? (technical problems solved)

FalkorDB is the only store: the company, incidents, the agents' memory, the tasks they coordinate through and the war-room history are all in one graph per company. Take it out and nothing runs: the UI refuses to start, and running agents pause until FalkorDB is back.

1. **Recall that follows the system, not the wording.** A variable-length `DEPENDS_ON` walk finds playbooks pinned 0–2 hops downstream of the alerting services, or on a datastore of the same kind. It found the right memory in its top 5 for 100% of incidents; text similarity (arm B, `vecf32` + `vec.cosineDistance` in the same database) found it for 55%.
2. **Crash-safe coordination without a queue.** Tasks are nodes. A claim is one Cypher query that sets a lease from FalkorDB's `timestamp()` (one clock for all workers) and increments a fencing epoch; every checkpoint and action checks the epoch, so a killed worker can never write after a takeover. Actions are keyed by intent under unique constraints, so a notification can't be sent twice. Under randomly expired leases: 0 duplicates, write p95 under 3.2 ms with 4 worker pairs.
3. **Memory that changes over time.** Facts have validity intervals and are superseded, never edited. Trust is updated in Cypher from each verdict; a playbook that misleads twice retires.
4. **Who to page right now.** A time-valid two-hop query (service → owning team → on-call person), and deploy history as `(:Person)-[:AUTHORED]->(:Change)-[:MODIFIED]->(:Service)`.
5. **Tenant isolation.** One graph per company, chosen from trusted config; no tool takes a graph name.
6. **Persistence.** RDB snapshots; the acceptance test restarts FalkorDB, then SIGKILLs a worker, and the replacement resumes at the next step.

All 73 queries are `.cypher` files indexed in `docs/QUERIES.md`, and the UI shows the Cypher behind every panel. We also found three FalkorDB issues, with reproductions in `docs/FALKORDB-FINDINGS.md`.

### Blog link

https://genziitian.github.io/Blastproof/blog/

*(Before submitting: GitHub → Settings → Pages → Deploy from a branch → `main` / `/docs`, wait a minute, then open the link in a private window. The page is `docs/blog/index.html`; `make ui` also serves it at http://localhost:8000/blog/. When the demo video is on YouTube, set `YOUTUBE_URL` near the top of the page's script.)*

## Part 2: Feedback

### What did you like about FalkorDB?

- Cypher that just works for graph questions: our whole recall (variable-length walk, validity filters, ranking) is one query.
- Speed: median reads and writes of about 0.35 ms from Python on a laptop, which let us checkpoint every agent step synchronously.
- `timestamp()` inside queries gave every worker the same clock for leases.
- Many graphs on one server: one graph per tenant cost nothing.
- Vectors in the same query language, so our text-memory baseline needed no second database.
- Easy to run: one Docker image with the Browser for inspecting graphs, and the embedded build (FalkorDBLite) for running the live tests without Docker.

### What improvements would you like to see?

- **AOF replay on 4.22.1:** after graph deletes and re-creates, replay diverged ("GRAPH.EFFECT references label 'Memory' (id 0)…") and the server shut down on every start. We switched to RDB snapshots.
- **Constraint creation written to the AOF three times** (4.18.3), with errors on replay.
- **A later `SET` clause reads values from before an earlier `SET`** in the same query, silently. Our trust update needed a `WITH` between clauses.
- **Developer experience:** a blocking option (or an error when the index is missing) for unique constraints; a `wait_until_ready()` in the Python client for the `LOADING` state after a restart; a client constructor that doesn't need the server to be up.

Reproductions: https://github.com/Genziitian/Blastproof/blob/main/docs/FALKORDB-FINDINGS.md

## Checklist (rule 10 and the form)

- [ ] Repository is **public**
- [x] README with setup instructions and the graph data model
- [x] The Cypher queries the product depends on (`docs/QUERIES.md`, all `*/queries/*.cypher`)
- [ ] Demo video on YouTube, public or unlisted (`docs/DEMO-SCRIPT.md`)
- [x] Complete local setup instructions (no live deployment)
- [ ] Both tracks ticked on the form
- [ ] AI-assistant disclosure confirmed by the team (README, "AI assistance"; the form has no field for it)
- [x] Only synthetic data in the graph
- [x] Main coding during the event (Oct 15–18)
- [ ] Both members have walked through `docs/TEAM-BRIEFING.md` (rule 12)
- [x] Frozen numbers from the final code in the README and this page (Oct 16 run)
