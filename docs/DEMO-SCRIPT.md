# Demo video: script and setup (about 3:20)

The story the video tells: **the problem → the idea → it working live → the proof**. The live part follows the plan's six demo moments. Everything on screen is the real system; nothing is scripted or mocked.

Record at 1920×1080, browser at 90% zoom. Keep a small Terminal in a corner running `make ui`, so the worker's death shows up as a real process exit. Speak slowly: about 140 words a minute. Record each scene separately and join them in editing; redo any scene that stumbles. Upload to **YouTube as public or unlisted** (the form only takes a YouTube link) and check the link in a private window.

## Before recording

```bash
cd Blastproof && source .venv/bin/activate   # the repo root (Windows: .venv\Scripts\activate)
docker compose up -d falkordb
make ui                                   # Terminal A, keep visible in a corner
curl -X POST localhost:8000/api/reset     # Terminal B: clean company_a
```

- Open http://localhost:8000 (the landing page) and refresh after the reset. Scenes 1–2 are recorded there; **Enter mission control** opens http://localhost:8000/mission-control for the rest.
- In mission control's **Director**: *scripted engineer* off (you play Priya), kill switch off for now.
- Header shows `FalkorDB 4.22.1 · connected`, `claude-haiku-5-5`, *demo timing*.
- Second tab: the FalkorDB Browser (http://localhost:3000), for scene 7.
- If anything misbehaves, `/classic` is the old all-panels view on the same data.

## The script

### Scene 1 · The problem (0:00–0:25)

**Screen:** the landing page hero: *On-call agents that remember every incident.* with the service graph replaying an incident on the right. Scroll slowly past the five stages (Remember · Recall · Check · Act · Learn).

**Say:**
> "When production breaks at 3 a.m., the on-call engineer usually starts from zero. What the team learned last month is in a postmortem nobody reads. AI agents have the same problem, plus two of their own: they trust old memory blindly, even when it doesn't fit, and when one crashes mid-investigation, the work is lost or someone gets paged twice."

### Scene 2 · The idea (0:25–0:50)

**Screen:** scroll to *01 · Recall* (the walk) and *02 · Check* (the two check cards), then click **Enter mission control**: *Break something and watch the agents work.*

**Say:**
> "Blast Radius is a team of on-call agents that share one FalkorDB graph. Every confirmed fix becomes a playbook pinned to the service that failed. On the next incident, agents find it by walking the dependency graph, check it against live evidence before trusting it, and coordinate through leased tasks in the same graph, so a crash is just a handover. This is a synthetic company: nine services, six datastores. Let's break it."

### Scene 3 · First incident, nothing in memory (0:50–1:20)

**Do:** Director → **s01**. Let *What happened* fill. When the war-room card appears, keep Priya's line in the box, click **Confirm**, then **Send** on the read-back.

**Screen:** three services pulse red; the headline says nothing is in memory; steps appear one by one on the left; the war-room card appears under the headline.

**Say:**
> "The orders database saturates. Nothing in memory yet, so the investigator works it out step by step, and every step is checkpointed to the graph. One page goes to Priya, who's on call. She confirms, and tells the agents how she wants database incidents handled next time: a ticket with the raw slow-query lines. The agent reads it back before saving it."

### Scene 4 · Memory is created, then a full restart (1:20–1:45)

**Do:** point at the **0.50** pin that dropped onto `postgres-orders`. Open **Memory** for three seconds (the playbook; Priya's approved preference superseding the agent's reading). Back to **Live**. In Terminal B: `docker compose down && docker compose up -d falkordb` (speed this up in editing).

**Screen:** the pin; the Memory tab; the graph card dims (*FalkorDB restarting…*) and comes back with *Memory survived the restart*.

**Say:**
> "The learner turned that investigation into a playbook pinned to postgres-orders, with where it came from. Priya's request is a sourced, versioned fact. Now a full database restart. Nothing reseeds. The memory is still there."

### Scene 5 · A related outage, and we kill the agent (1:45–2:25)

**Do:** Director → switch on **Kill the investigator after step 3** → **s04**. Don't touch anything until the takeover. When the war-room card appears, clear the box and **Confirm**. Open the *page* step.

**Screen:** the recall path draws from `payments-gw` to `postgres-payments`, *1 hop · same kind of datastore*; the dashed line to `postgres-orders` shows where the playbook was learned; the checking card ticks off each check; after step 3 one agent shows **SIGKILL** and its lease ring drains; the headline says *took over at step 4, not from scratch* and the other agent shows **e1 → e2**; the envelope flies to Priya (**1 notification**); the pin counts up **0.50 → 0.67**.

**Say:**
> "Now the payments database saturates, with alerts worded differently. A text search wouldn't match it. The graph does: the orders playbook is recalled for payments, one hop from the alerts, same kind of datastore. Before trusting it, the agent checks each condition against live evidence."
>
> (on the kill) "Here we kill the investigator mid-task, a real SIGKILL. Its lease runs out, and the second worker takes over at step 4 under a new fencing epoch, not from scratch. The dead one can never write again. Priya gets exactly one ticket, with the raw lines, the way she asked. The playbook helped, so its trust goes up."

### Scene 6 · Memory that doesn't apply (2:25–2:50)

**Do:** Director → **s05**. Confirm when asked.

**Screen:** the checking card: *No deploy on checkout-api in the last 2 h* **✕ observed 1 deploy**, *Not applicable · trust unchanged*; the root turns out to be `checkout-api`, a bad deploy.

**Say:**
> "Same checkout symptoms, different cause. The database playbook is recalled again, but its first check fails: checkout-api was just deployed. So it's ruled out on evidence, its trust untouched, and the agent finds the bad deploy instead. Memory that doesn't fit never steers the investigation."

### Scene 7 · The proof (2:50–3:20)

**Do:** **Results** tab (hold three seconds on the 71%), then the charts. Back on Live, press **▶** on the graph card to replay s04 from its stored steps, then click **{ } query** → *recall: walk downstream from the alerts*. Optionally flash the FalkorDB Browser tab.

**Say:**
> "We measured it on thirty incidents, with the same model and tools, changing only how memory is retrieved. Graph memory made 71% fewer model calls than no memory, solved twenty incidents with no model call at all, and found the right memory every time, against 55% for text similarity. Zero duplicate pages, even with leases expiring at random, and a deliberately wrong playbook retired itself after misleading twice. Every panel is a Cypher query on FalkorDB, and one command reruns all of it. That's Blast Radius."

## What each scene proves (for Q&A)

| Scene | Plan moment | Track 02 focus point |
|---|---|---|
| 3 | 1 · first incident | Shared state and handoffs; persistent conversation |
| 4 | 2 · memory is created; restart | Episodic, semantic, procedural memory; persistence |
| 5 | 3 · related outage + 4 · takeover | Recall by graph; fencing and handoffs; preferences applied |
| 6 | 5 · memory that doesn't apply | Memory checked before trust; updates over time |
| 7 | 6 · proof | High-concurrency reads and writes; separate memory per tenant |

## If something goes wrong

- **The kill fired too early or not at all:** it's one shot per incident; switch it on again and run s04 again (each run is a new incident).
- **The investigator is slow on s01:** that's Claude thinking; let it run and cut in editing.
- **FalkorDB takes a moment after the restart:** the page waits and recovers by itself; refresh if needed.
- **Wrong state:** `curl -X POST localhost:8000/api/reset` (or Director → Reset company) and start again.

## The 60-second GIF for the README

Scenes 5 and 6 only, no narration: s04 with the armed kill (checking card → SIGKILL → lease drains → takeover → envelope → trust count-up), then s05 (ruled out). Save as `docs/img/demo.gif` and put it at the top of the README in place of the screenshot.
