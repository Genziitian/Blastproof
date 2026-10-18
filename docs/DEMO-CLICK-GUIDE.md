# Blast Radius — exact recording click guide

Published demo: https://youtu.be/ubFTOB0ZIh0

Open http://localhost:8000/mission-control. This is the full interactive local portal. The hosted site auto-plays and hides manual controls.

Checked the current local UI without starting scenarios or resetting data. Current state: company_a has previous incidents and 3 playbooks, including a planted wrong one; Scripted engineer OFF; kill not armed; runtime model header claude-haiku-5-5. The separate Results benchmark is rule-based. Match captions to these separate sources.

## Screen map

| Where | What is accessible |
|---|---|
| Top centre: Live | Incident investigation, graph, war room and agent cards. |
| Top centre: Memory | Saved playbooks, trust, provenance and versioned engineer preferences. |
| Top centre: Results | Selected benchmark, load, tenant isolation, stale-write and retirement evidence. |
| Top right: Director ▾ | s01–s05, armed kill, Scripted engineer, on-call changes and local reset. |
| Live, right: Service graph | This is the dependency graph: services, datastores, dependency edges, recall paths and playbook pins. |
| Service graph header: { } query | The actual Cypher drawer. ‘this panel’ shows service_map.cypher; ‘recall: walk downstream from the alerts’ shows recall.cypher; ‘recall: same kind of datastore’ shows recall_kind.cypher. |
| Live, left: Checked … step | Memory Lens. Shows What, Why recalled, Evidence and Afterwards. Click the step heading if collapsed. |
| Live, left beneath headline | War room appears only when an incident needs confirmation or a preference read-back. |
| Live, bottom left: Agents | Worker state, lease countdown and fencing epoch. Investigation step rows show checkpoints. |
| Live, top-left incident dropdown | Select an older incident to inspect or replay. |
| Service graph header: ← ▶ → / Live | Replay saved steps; Live exits replay. |
| Top: FalkorDB connected | Link to the local FalkorDB Browser at http://localhost:3000. The in-product query drawer is enough for the main video. |

If the graph is not on the right, enlarge the browser. At viewport widths of 1100 px or less it moves below the investigation. The left evidence list also has its own scroll area: place the pointer over the evidence cards to scroll within it.

## Recording order

### 0. Prepare a fresh local take

Your current local history is not empty. If you want the exact cold-start script, reset only this disposable local demo history: Director ▾ → Reset company → Click again to reset. This removes the local company's existing incidents and learned memory, then restores the synthetic world. I have not performed this reset. If you need to preserve this history, leave it and film a separate clean local instance instead.

Director ▾ → keep Scripted engineer OFF for manual Confirm and Send; keep Arm the kill OFF until s04. Close the menu with Director ▾ again. Check the model name in the top bar: it currently says claude-haiku-5-5, so do not caption this running local session as deterministic unless you restart it with the model disabled. The Results tab independently labels its saved deterministic benchmark.

### 1. Opening: graph and how the system works

1. Click Live.
2. Show the Service graph on the right and the three introductory steps on the left when the company is clean.
3. Point at nodes and dependency edges; no scenario needs starting yet.
4. Click { } query in the Service graph header.
5. Click recall: walk downstream from the alerts. The file path is memory/queries/recall.cypher.
6. Show the DEPENDS_ON walk for 2–3 seconds.
7. Optional: click recall: same kind of datastore to explain transfer from orders to payments.
8. Click Close at the top of the drawer.

### 2. First incident: s01

1. Director ▾ → s01 Orders DB saturates (first time).
2. Watch the left investigation steps and the graph highlight postgres-orders.
3. When War room / Confirm diagnosis? appears, inspect the prefilled message asking for tickets and raw logs, then click Confirm.
4. Wait for Is this what you meant? Inspect the preference read-back and the affirmative Reply, then click Send. If Reply is empty, enter Yes before Send.
5. Wait for learning to finish.
6. Click Memory at the top.
7. Find db-saturation pinned to postgres-orders. In a clean run its initial trust is 0.50.
8. Click the playbook row to expand Rule out first and Then expect.
9. Scroll down to Engineer preferences. Show engineer-approved v2, Priya’s original message, source incident and superseded v1.
10. Click Live to return.

### 3. Persistence shot

Use docs/blog/media/restart.mp4 for the genuine recorded local persistence test. Show before/reconnect/after and caption Recorded local persistence test — no reseed. Shortened waits should be labelled. Do not use the public app’s reset loop as persistence evidence.

### 4. Related incident and real kill: s04

1. Live → Director ▾.
2. In Kill the investigator after step, enter 3.
3. Turn Arm the kill ON.
4. Click s04 Payments DB saturates, new wording.
5. Watch the left Checked … step: that expanded card is Memory Lens. Show Why recalled and the observed checks.
6. Show SIGKILL and the lease draining in the Agents cards. Wait; do not click Kill again.
7. Show replacement at step 4 / epoch e2 after e1 checkpoints. Use the investigation/checkpoint details and the worker card.
8. When the war-room confirmation appears, click Confirm.
9. In the left steps, click the 1 ticket sent to priya row if collapsed, then The ticket as sent to show its payload/raw logs.
10. Expand the confirmation/conversation step to show the earlier preference citation/history as needed.
11. Show the learned outcome: in the clean sequence trust goes 0.50 → 0.67. Read actual displayed values if reusing older history.

### 5. Wrong fit: s05

1. Director ▾ → s05 Checkout errors again, different cause.
2. In Checked … / Memory Lens, show deploys == 0 versus observed 1 and ruled out/not applicable.
3. Show the checkout-api bad-deploy diagnosis, then Confirm.
4. Show that the database playbook’s trust did not change from this rejected application.
5. Do not use Plant a wrong playbook during this short sequence. The deliberate misleading-memory retirement is a separate M5 benchmark.

### 6. Proof screen

1. Click Results.
2. Show run name/date and Model: rule-based. Current selected run is 2026-10-18T15-42-49Z-rule-based, 12-step budget.
3. Show 100% graph diagnosis accuracy and 30/30 in all three arms.
4. Show Tool calls: no memory 5.97, text 7.63, graph 5.07.
5. Show 2 uses before the seeded wrong playbook retired.
6. Scroll to Tenant isolation: Passed / 0 leaked markers and Stale writes rejected: 5/5.
7. Scroll to Latest load run: each selected configuration completes 20/20 with Duplicates = 0.
8. Return to Live for the closing shot; show the live website URL on the end card.

The 71% model-call saving is from the separate Oct 16 recorded model benchmark. Use a dated historical-results shot if mentioning it. The current Results headline is diagnosis accuracy, not model-call savings.

## If you miss the takeover while speaking

Select the s04 incident using the dropdown above the left headline. In the Service graph header, click ▶ to replay its saved events, or ← / → to step through. Label it Recorded incident replay. Click Live in the graph header to return. No additional kill is needed.
