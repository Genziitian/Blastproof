# Submission: text to paste

Deadline: **Sun Oct 18, 11:59 PM IST**; target 8 PM. Checklist (rule 10) at the bottom.

**Project name:** Blast Radius

**Tagline (one line):** On-call agents that remember previous incidents, check whether that memory still applies, and show how it changed the next investigation, even after a restart.

**Tracks:** Track 02: Agent Memory and Coordination. Add Track 01 (Agents That Act on Connected Data) only if the FalkorDB Discord says entering both is fine; the rules require naming every track entered.

**Repository:** https://github.com/Genziitian/Blastproof

**Demo video:** *(link after upload)*

**Live deployment:** none; complete local setup in the README (`make db schema seed ui`).

**Team:** Genz IITIAN *(names)*

## Short description (about 100 words)

Blast Radius is a team of on-call agents that share one FalkorDB graph per company. When an incident is confirmed, its investigation becomes a playbook pinned to the failing node. Next time, agents recall playbooks near the alerting services by walking the dependency graph, check each against live evidence before trusting it, and lower trust in any that mislead. What engineers say in the war room becomes sourced, conditional preferences. Agents coordinate only through fenced tasks in the graph, so a worker killed mid-investigation is taken over from its last checkpoint without duplicate pages. Everything survives a full restart.

## Longer description

**What it does.** Agents investigate simulated outages from observable evidence (metrics, logs, deploys, dependency health) in a 15-node synthetic company. A confirmed investigation becomes a sourced playbook: what to rule out first, what to expect, and where it came from. On the next incident, the investigator recalls playbooks pinned 0–2 hops downstream of the alerting services, or on another datastore of the same kind, and checks their preconditions with plain tool calls before trusting them. Memory that misleads loses trust and retires. The responder pages whoever owns the failing node and is on call at that moment, the way they asked, citing the message where they asked.

**How FalkorDB is used.** Everything is in the graph: the company (services, dependencies, owners and on-call with validity intervals, deploy history), incidents and immutable decision records, the tasks the agents coordinate through (fenced leases using `timestamp()`, checkpoints, intent-keyed actions), versioned memory (playbooks, facts with supersession), and the war-room conversations. Recall is a variable-length `DEPENDS_ON` walk, who-to-page a time-valid two-hop query, blast radius up to four hops. One graph per tenant, chosen from trusted config, never by the model. All 73 queries are `.cypher` files, indexed in `docs/QUERIES.md`; the UI shows the Cypher behind every panel.

**Results (synthetic 30-incident benchmark, Claude Haiku 5.5, only retrieval differs between arms).** *(Replace with the frozen Saturday numbers.)* No memory, text memory and graph memory reached 30/30, 29/30 and 30/30. Graph memory used 72% fewer model requests than no memory (52 vs 185), solved 21 of 30 incidents without any model call, and found the right memory in its top 5 every time, against 48% for text similarity. 0 misleading uses, 0 duplicate notifications under randomly expired leases, 0 leaks between tenants, and a deliberately wrong playbook retired after two misleading uses. The acceptance test kills a real worker process after a full database restart; its replacement resumes at the next step.

**What we found in FalkorDB.** AOF replay diverging on 4.22.1 after graph deletes and re-creates (the server then refused to start), unique-constraint creation written to the AOF three times, and a later `SET` clause reading values from before an earlier one; reproductions in `docs/FALKORDB-FINDINGS.md`.

**AI assistance.** Claude for pair-programming, tests and verification; ChatGPT and Gemini for plan reviews; Claude Haiku 5.5 inside the product. Details in the README.

## Checklist (rule 10)

- [ ] Repository is **public**
- [x] README with setup instructions and the graph data model
- [x] The Cypher queries the product depends on (`docs/QUERIES.md`, all `*/queries/*.cypher`)
- [ ] Demo video showing the working project (`docs/DEMO-SCRIPT.md`)
- [x] Complete local setup instructions (no live deployment)
- [ ] Every track named on the form
- [ ] AI-assistant disclosure confirmed by the team (README, "AI assistance")
- [x] Only synthetic data in the graph
- [x] Main coding during the event (Oct 15–18)
- [ ] Every member has walked through `docs/TEAM-BRIEFING.md`
- [ ] Frozen numbers from the final commit in the README and this page
