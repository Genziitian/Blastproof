# Blast Radius — 3-minute English + Hinglish demo script

**Published demo:** https://youtu.be/ubFTOB0ZIh0

**Target runtime: 3:00. Narration: 341 words.** Speak only the English narration. The Hinglish column explains the meaning and actions for rehearsal. Timecodes are editing targets, not a guarantee that an uninterrupted run finishes in three minutes. Record complete genuine sequences first, then edit to the timeline and rehearse.

**Recording route:** Use local Mission Control at http://localhost:8000/mission-control for Director, Confirm, Send and the armed kill. The public site https://blast.genziitian.in/mission-control runs the actual sequence automatically with a scripted engineer; its write controls are intentionally hidden. If filming the public site, wait for s01 → s04 → s05 instead of following local click instructions, and label it ‘Live system • scripted engineer • deterministic planner’. Keep one full round together so source incident IDs remain consistent.

**What is real:** OS workers, SIGKILL, FalkorDB reads/writes, stored memory, checkpoints, handoffs and evaluation artifacts. **What is synthetic:** company, incidents, evidence and engineer persona. Tickets/pages are logical Action records in this product, not proof of delivery through an external provider. The current planner is deterministic; optional model support and the historical model benchmark are separate.

**Title card:** Blast Radius — Agents that remember and recover.

## 1 · The problem · 0:00–0:25

| English — say this | Hinglish — samajhne ke liye | Screen — show this while speaking |
|---|---|---|
| “When production breaks at three a.m., the on-call engineer starts from zero. Last month’s fix is buried in a postmortem. Agents face two more problems: old memory may not fit, and a crash can lose the investigation or repeat a notification. We built Blast Radius to solve that.” | Raat ko outage aaya toh engineer aur agent dono dobara investigation shuru karte hain. Purana solution notes mein pada hai. Bina check kiye purani memory use karna galat ho sakta hai; agent crash ho toh kaam repeat hota hai. Isi problem ko hum solve kar rahe hain. | Local Mission Control → Live tab, before starting an incident. Keep the dependency graph and right-hand learning loop visible. Point briefly at the graph; do not click through menus while introducing the problem. |

**Action samjho:** Local portal ka Live tab kholo. Abhi incident start mat karo. Graph aur right-side process dikhne do; opening ke waqt screen stable rakho.

**On-screen caption:** Blast Radius · Remember. Verify. Resume.

## 2 · The idea and the real graph · 0:25–0:45

| English — say this | Hinglish — samajhne ke liye | Screen — show this while speaking |
|---|---|---|
| “Four agent roles share one FalkorDB graph per company. It stores incidents, conversations, playbooks, and leased tasks. Confirmed fixes become reusable memory; relationships determine what gets recalled. This demonstration uses synthetic incidents, real workers, and real graph reads and writes.” | Triage, investigator, responder aur learner ek company graph share karte hain. Memory aur coordination dono FalkorDB mein hain. Incident inputs synthetic hain, lekin workers sach mein execute ho rahe hain aur database par actual reads/writes ho rahi hain. | Point to the learning loop: remember → recall/check → act/learn. Open ‹› beside Dependency graph for a brief real Cypher view, then close it. Keep a persistent small caption: ‘Synthetic inputs • deterministic planner • real execution’. The company has nine services and six datastores; no need to read every node name. |

**Action samjho:** Right-side learning steps se graph ki taraf pointer le jao. Dependency graph ke ‹› se actual query dikhao, phir close karo. Caption se clear karo ki inputs synthetic hain aur current planner rule-based hai.

**On-screen caption:** Track 02 · Agent Memory and Coordination | Synthetic inputs · deterministic planner · real execution

## 3 · First incident: learn from experience · 0:45–1:10

| English — say this | Hinglish — samajhne ke liye | Screen — show this while speaking |
|---|---|---|
| “First, the orders database saturates. With no applicable playbook, the investigator checks fresh evidence and saves each step. Priya confirms the diagnosis and requests tickets with raw logs for future database incidents. The agent reads that back before approval. The learner saves a sourced playbook and a versioned preference.” | Pehli baar database problem aati hai, toh agent evidence dekh kar cause nikalta hai. Priya diagnosis confirm karke bolti hai: next time ticket aur raw logs chahiye. Agent apni understanding read back karta hai. Approval ke baad reusable playbook aur preference save hoti hai. | Director → choose s01. Close Director. Show checkpoints, postgres-orders diagnosis, and the war-room card. Click Confirm; inspect the prefilled preference reply and read-back; click Send to approve it. Switch to Memory and show the sourced playbook plus the approved preference. Use cuts between genuine completed states to fit 25 seconds. |

**Action samjho:** Director mein s01 chalao. War room mein Confirm karo. Jo reply/read-back visible hai usko padh kar Send karo. Memory tab par playbook, source incident aur approved preference dikhao. Har action uski actual screen aane par hi karo.

**On-screen caption:** Episodic: incident history · Semantic: preferences · Procedural: playbooks

## 4 · Prove persistence · 1:10–1:25

| English — say this | Hinglish — samajhne ke liye | Screen — show this while speaking |
|---|---|---|
| “Now we restart FalkorDB without reseeding. The saved playbook, conversation, and progress remain. Memory survives beyond the process that created it. This is a recorded local persistence test.” | Ab database ko restart karne ke baad wahi saved memory aur history wapas milti hai. Hum data dobara seed nahi kar rahe. Is shot ko recorded local test bolna hai; public website ki reset loop ko persistence proof mat bolna. | Insert the genuine local restart recording at docs/blog/media/restart.mp4. Show memory before, database unavailable/reconnecting, and retained records after. Overlay ‘Recorded local persistence test • no reseed’. If editing out the wait, add ‘Restart wait shortened’. For a new local take only: run docker compose down && docker compose up -d falkordb from the code folder; do not seed and do not use -v. Never run that command against the shared VPS for this recording. |

**Action samjho:** Existing real restart clip lagao: pehle memory, phir DB reconnect, phir wahi memory. Caption poore shot mein rakho. Naya take chahiye toh sirf local DB restart karo; seed command ya -v mat chalao.

**On-screen caption:** Recorded local persistence test · no reseed

## 5 · The signature moment: memory plus takeover · 1:25–2:00

| English — say this | Hinglish — samajhne ke liye | Screen — show this while speaking |
|---|---|---|
| “Next, payments fails with different alert wording. The graph recalls the orders playbook through the datastore relationship and checks it against current evidence. We kill the investigator after checkpoint three: a real SIGKILL. Its lease expires; another worker resumes at step four under a new epoch. Stale writes are rejected. One ticket is recorded with Priya’s requested logs, and successful reuse raises trust.” | Payments database par related issue aata hai. Words alag hain, lekin graph relation se orders wala playbook milta hai. Uske checks chal rahe hote hain tab worker ko sach mein kill karte hain. Lease expire hone par doosra worker saved step ke baad continue karta hai. Purane epoch ki writes reject hoti hain. Ticket action ek hi record hota hai aur trust badhta hai. | Back to Live. Director → set ‘Kill the investigator after step’ to 3 → arm the kill → choose s04. Show Memory Lens and its observed checks; then SIGKILL, lease countdown, step 4, and e1 → e2 in the agent timeline. Do not click another kill or reset. Wait for the war-room card and Confirm. End on the single ticket action, raw-log text, s01 preference citation, and trust 0.50 → 0.67. Capture the whole real sequence first; edit it to 35 seconds without swapping the event order. |

**Action samjho:** Director mein kill-after 3 set karke arm karo, phir s04 chalao. Checking → kill → lease drain → replacement step 4 ka order preserve karo. Doosra kill/reset mat click karo. Diagnosis aane par Confirm karo; ek ticket aur trust change dikhao.

**On-screen caption:** Checkpoint 3 → SIGKILL → checkpoint 4 | epoch 1 → 2 | one logical ticket action

## 6 · Reject memory that does not apply · 2:00–2:20

| English — say this | Hinglish — samajhne ke liye | Screen — show this while speaking |
|---|---|---|
| “Now checkout fails for a different reason. The database playbook is recalled, but a recent deploy fails its first check. The memory is marked not applicable, its trust stays unchanged, and investigation identifies the bad deploy. The agent learns a different lesson.” | Symptoms milte-julte hain, par reason alag hai. Recent deploy milne se database playbook ka check fail hota hai. Agent us memory ko follow nahi karta; uska trust bhi punish nahi hota, kyunki use apply hi nahi kiya. Investigation bad deploy find karti hai. | Director → s05. Hold on ‘deploys == 0 / observed 1’ and ‘not applicable’. Show the relevant database playbook’s unchanged trust. Then show checkout-api / bad deploy diagnosis, Confirm, and the resulting new lesson. Do not describe this as the wrong-playbook retirement test: that is a separate M5 benchmark. |

**Action samjho:** s05 chalao. Failed deploy check aur not applicable par 2 seconds ruko. Wahi DB playbook ka unchanged trust dikhao. Phir bad-deploy diagnosis aur Confirm. M5 retirement ko is incident ka outcome mat bolo.

**On-screen caption:** Check fails → memory ruled out → trust unchanged → new diagnosis

## 7 · Proof and closing · 2:20–3:00

| English — say this | Hinglish — samajhne ke liye | Screen — show this while speaking |
|---|---|---|
| “Our latest deterministic benchmark covers thirty synthetic incidents. All three setups diagnose thirty out of thirty correctly. Graph memory averages about five tool calls per incident, versus six without memory. The measured load runs have zero duplicate notifications; tenant checks find zero leaks; all five stale writes are rejected. A deliberately wrong playbook retires after two misleading uses. The code, queries, and live deployment are public. Blast Radius: remember, verify, resume.” | Latest run rule-based hai, paid model wala run nahi. Teeno setups ne 30 mein 30 diagnoses sahi kiye. Graph memory mein average 5.07 tool calls hain, no-memory mein 5.97. Load test mein duplicate action zero, tenant markers leak zero, aur stale writes 5/5 reject. Alag M5 test mein wrong playbook do misleading uses ke baad retire hota hai. Claims sirf tested workload ke hain. | 2:20–2:30 Results → show selected run/date/model and accuracy; 2:30–2:36 show mean tool calls A 5.97 / C 5.07; 2:36–2:48 show load, isolation and fencing cards; 2:48–2:53 show M5 ‘2 uses’ retirement evidence; 2:53–3:00 close on graph, then end card. Stop narration by about 2:57 and hold the final card silently. End card: Blast Radius / Team Blastproof / Track 02: Agent Memory and Coordination / blast.genziitian.in / github.com/Genziitian/Blastproof / ‘AI assistance disclosed in README’. The draft additionally names Track 01: include it on the final submission and optionally the end card if entering both. |

**Action samjho:** Results mein pehle run ka naam/date/model dikhao, phir accuracy aur tool calls. Neeche load, isolation aur fencing cards dikhana. M5 alag benchmark hai. Last 3 seconds end card hold karo. Latest screen par 71% mat bolo; woh older model run ka result hai.

**On-screen caption:** Latest deterministic run · synthetic benchmark | 30/30 per arm · 0 duplicates · 0 tenant leaks · 5/5 stale writes rejected

## Preparation before pressing Record

1. Use the local portal for manual controls, with the deterministic planner selected. If starting it yourself, use `PUBLIC_MODE=0 LLM_MODEL= TIMING_PROFILE=demo .venv/bin/python -m web.app --company a --port 8000` after completing the README setup. Keep model keys and environment files off-screen.
2. Use a disposable local demo company with no learned incident yet. Turn Scripted engineer OFF in Director if you plan to click Confirm and Send yourself. Reset only the local disposable company if needed; that deletes its previous demo history.
3. Capture s01 → memory → restart proof → s04 → s05 in that order. Keep the s01 source ID matching the preference citation seen in s04.
4. For restart evidence, use the existing genuine local clip, or film a local restart without reseeding. The public loop intentionally resets between rounds and at app startup, so public reset/startup is not no-reseed persistence evidence.
5. For s04, arm the kill **before** starting the incident. Once the kill happens, let the lease drain. The replacement must visibly write checkpoint 4 with epoch 2.
6. Record voiceover separately. Use 1080p footage, readable text and gentle zooms; label shortened waits. Do not fabricate logs, query outputs, success cards or event order.
7. Before filming Results, reread its selected run and date. This script matches `2026-10-18T15-42-49Z-rule-based`, 12-step budget, hash-256 text baseline. If the selected run changes, update the narration too.
8. The published demo is linked above. Verify anonymous playback, copy its URL into the final submission form, and submit before the official deadline. A script does not replace the working video.

## If you want to mention the 71% result

Use a separate, explicitly dated shot of the blog Results section or the Oct 16 model benchmark summary. Do not hold on the latest deterministic Results tab while reading these numbers.

**Optional historical narration:** “In our recorded October sixteenth model benchmark, graph memory used fifty-five model requests versus one hundred ninety-two without memory: seventy-one percent fewer, with thirty out of thirty diagnoses correct in both. This is a separate run from today’s deterministic demo.”

**Hinglish:** Yeh October 16 ka saved model run hai. Isko current rule-based run ka live saving mat bolo. Source/date screen par dikhao. Is line ko add karna hai toh scene 7 ke equivalent narration ko replace karo aur final cut dobara time karo; seedha extra line jodoge toh video three minutes se lamba hoga.

## Five explanations to rehearse for judges

| Judge asks | Answer in plain English | Hinglish reminder |
|---|---|---|
| Why FalkorDB? | Memory recall walks service dependencies. The same graph stores tasks, leases, checkpoints and conversations. Removing the database breaks these central workflows. | Graph sirf picture nahi; recall aur coordination isi par depend hain. |
| What are the three memory types? | Episodic: past incidents and checkpoints. Semantic: time-valid engineer preferences. Procedural: playbooks with executable checks. | Kya hua / kya fact hai / kaise solve karna hai. |
| What prevents an old worker from writing? | A fenced write checks task status, owner, lease time and epoch. A takeover increments the epoch, so old claims fail. | Purane claim ka epoch naya epoch se match nahi karega. |
| What does zero duplicates mean? | The tested runs created one logical action per notification intent. It does not prove exactly-once delivery through an external paging provider. | Action record ka proof hai; external pager integration ka nahi. |
| Why can memory be rejected without losing trust? | A failed precondition means the playbook was not applied. A misleading verdict applies only when following it produced a wrong diagnosis. | Apply nahi hua toh blame nahi; follow karke galat hua toh trust kam. |
