# Demo video: script and setup (3 minutes)

The plan's six moments, mapped to the UI. Record at 1920×1080 with the browser at about 90% zoom so the whole Incidents view fits. Keep a Terminal visible in a corner running `make ui`, so the worker's death shows up as a real process exit. Record moments 3–4 twice and keep the cleaner take. Upload to **YouTube as public or unlisted** (the form only takes a YouTube link) and open the link in a private window to check it plays.

## Before recording

```bash
cd ~/Desktop/BlastRadius-GraphHacks/code && source .venv/bin/activate
docker compose up -d falkordb
make ui                                   # Terminal A, keep visible
curl -X POST localhost:8000/api/reset     # Terminal B: clean company_a
```

- Browser: http://localhost:8000, refresh after the reset. In **Director**, leave *scripted engineer* off (you play Priya) and *captions* on: the caption bar says each moment in one sentence, so the video reads even without narration.
- Check the header: `FalkorDB 4.22.1 · connected`, `claude-haiku-5-5`, and the *demo timing* tag. `/classic` is the old all-panels view if anything misbehaves.
- Have the FalkorDB Browser (http://localhost:3000) open in a second tab for moment 6.

## Moments

| Time | Moment | Do | Say |
|---|---|---|---|
| 0:00–0:10 | Hook | Incidents view, empty | "Our on-call agents remember past incidents, check that the memory still applies, and show how it changed the next investigation, even after a restart. Everything lives in FalkorDB." |
| 0:10–0:40 | **1. First incident** | Director → **s01**. Let *What happened* fill (Claude investigates from scratch, each step checkpointed). When the war-room card appears, keep Priya's line, click **Confirm**, then **Send** on the read-back. | "Orders DB saturates. Nothing in memory yet, so the investigator works it out step by step, checkpointing every tool call to the graph. Priya confirms and tells the responder how she wants DB incidents handled. It reads that back before saving it." |
| 0:40–0:55 | **2. Memory is created** | Point at the **0.50** pin that dropped onto `postgres-orders`. Open the **Memory** tab for 3 seconds: the playbook (*learned from s01*; click it for its checks) and Priya's preferences (her approved version superseding the agent's reading). Back to **Live**. | "The learner turned that investigation into a playbook pinned to postgres-orders, with what to rule out first and where it came from. Her preference is a sourced, versioned fact." |
| 0:55–1:35 | **3. Restart, then a related outage** | Terminal B: `docker compose down && docker compose up -d falkordb` (speed this up in editing). The stage dims (*FalkorDB restarting…*) and comes back with *Memory survived the restart*. Director → switch on **Kill the investigator after step 3** → **s04**. The recall path draws from `payments-gw` to `postgres-payments`, *1 hop · same kind of datastore*, and the checking card ticks off each check. | "Full database restart; nothing reseeds. Now the payments database saturates, with alerts worded differently. The agent recalls the orders playbook by walking the dependency graph: same kind of datastore, one hop from the alerts. It checks every precondition against live evidence before trusting it." |
| 1:35–2:00 | **4. Takeover** | After step 3 the worker is SIGKILLed: its card shows **SIGKILL** and the lease ring drains over 6 s; the other card shows **took over** and **e1 → e2**, resuming at step 4. Terminal A shows the process exit. The envelope flies to Priya (**1 notification**). Clear the message box and **Confirm**. Open the page step: *ticket, per your note in incident s01*. The pin counts up **0.50 → 0.67**. | "We killed the investigator mid-investigation, a real SIGKILL. The lease runs out, a second worker takes over under a new fencing epoch and continues from step 4, not from scratch. The dead one could never write again. Priya gets exactly one ticket, with raw lines, the way she asked, citing incident s01." |
| 2:00–2:30 | **5. Memory that doesn't apply** | Optional first: click `checkout-api` on the graph and **Move** ownership to `payments`. Director → **s05**. The checking card: *No deploy on checkout-api* ✕ observed **1 deploy**, *Not applicable · trust unchanged*. The correct cause is a bad deploy. If you moved ownership, the page goes to the new owner. | "Same checkout errors, different cause. The old database playbook is recalled, but its first check fails: there was a deploy 12 minutes ago. It's ruled out on evidence, trust untouched, and the agent finds the bad deploy." |
| 2:30–3:00 | **6. Proof** | **Results** tab: the three-arm table, recall@5 bars, M5, concurrency. Back on Live, click **‹›** next to *Dependency graph* → *recall: walk downstream from the alerts*. Optionally flash the FalkorDB Browser tab. | "Same model and tools, only retrieval differs: graph memory needed 71% fewer model calls than no memory and found the right memory every time, against 55% for text. Zero duplicate pages under chaos, zero leaks between tenants, and a deliberately wrong playbook retired after misleading twice. Every panel is a Cypher query on FalkorDB, and one command reruns it all." |

## If something goes wrong

- **The kill fired before step 3 shows:** it's armed per incident; tick it again and click s04 again (each click is a new incident).
- **The investigator is slow on s01:** that's Claude thinking; let it run, or cut in editing.
- **FalkorDB takes a moment after the restart:** `make ui` and the page wait for it; refresh once it's up.
- **Wrong state:** `curl -X POST localhost:8000/api/reset` and start again.

## The 60-second GIF for the README

Moments 3 and 5 only: s04 with the armed kill (checking card → SIGKILL → lease drains → takeover → envelope → trust count-up), then s05 (ruled out). Save it as `docs/img/demo.gif` and replace the screenshot at the top of the README.
