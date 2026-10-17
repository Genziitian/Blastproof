# Cypher queries

Every query the product runs lives in a `.cypher` file; this index is generated from each file's leading comment (`python -m scripts.query_index`). Comment lines are stripped before a query is sent (`common/db.py`).

73 queries.

## Memory: recall (A1, A1b), trust (A2), facts (A3), playbooks (A4)

| Query | What it does |
|---|---|
| [`memory/queries/add_provenance.cypher`](../memory/queries/add_provenance.cypher) | Another confirmed incident supports an existing playbook: record it as a source and pin the playbook to this incident's root too, instead of writing a duplicate. (A bad-deploy playbook learned on checkout-api then also applies to search-svc.) |
| [`memory/queries/bind_path.cypher`](../memory/queries/bind_path.cypher) | Arm B binding only: routes from an alerting service to a target, so the shared precondition executor can bind $alerting and $caller. |
| [`memory/queries/datastores_of_kind.cypher`](../memory/queries/datastores_of_kind.cypher) | Arm B targets: every datastore of a kind (text retrieval has no notion of "nearby"). |
| [`memory/queries/fact_check.cypher`](../memory/queries/fact_check.cypher) | A3 step 1 (read-only): validate scope, source and any existing version first, and count earlier versions of this lineage. |
| [`memory/queries/fact_supersede.cypher`](../memory/queries/fact_supersede.cypher) | A3 step 2: create one new version (safe to retry) and close older ones. Run only after fact_check says scope and source exist and the id is new or carries the same payload_hash. |
| [`memory/queries/feedback.cypher`](../memory/queries/feedback.cypher) | A2: one verdict per USED edge, applied once; a retried call changes nothing. $verdicts = [{id, target, verdict: 'helped' / 'misled' / 'not_applicable'}] Only memories that were followed can be credited or blamed. |
| [`memory/queries/playbook_by_signature.cypher`](../memory/queries/playbook_by_signature.cypher) | Learner: the oldest active playbook with this signature, so a repeat adds a source instead of a duplicate playbook. |
| [`memory/queries/playbook_texts.cypher`](../memory/queries/playbook_texts.cypher) | Arm B indexing: what each active playbook says, where it is pinned and which alerts it was learned from, to embed as text. |
| [`memory/queries/playbooks_by_id.cypher`](../memory/queries/playbooks_by_id.cypher) | The full records of recalled playbooks, so their checks can be run. |
| [`memory/queries/recall.cypher`](../memory/queries/recall.cypher) | A1, 1-2 hops: walk DOWNSTREAM only (an alerting service fails because something it depends on failed), so hub services don't drag in unrelated memory. If *0..2 works in your FalkorDB version, this and recall_direct can merge. |
| [`memory/queries/recall_direct.cypher`](../memory/queries/recall_direct.cypher) | A1, 0 hops: memories pinned to an alerting service itself. $scenario_now is SIMULATED time, so a replayed scenario never sees later memory. |
| [`memory/queries/recall_kind.cypher`](../memory/queries/recall_kind.cypher) | A1b: playbooks learned on another datastore of the same kind (e.g. any postgres), at half weight. Restricted to Datastore so service-level playbooks stay specific. |
| [`memory/queries/set_embedding.cypher`](../memory/queries/set_embedding.cypher) | Arm B indexing: store a playbook's text embedding (index data, not content). |
| [`memory/queries/vector_recall.cypher`](../memory/queries/vector_recall.cypher) | Arm B retrieval: nearest memories to the alert text by exact cosine distance, with the same validity rules as graph recall. Exact search over a few dozen memories is cheap, and exact by definition, so this arm is never handicapped by approximate search. |
| [`memory/queries/write_playbook.cypher`](../memory/queries/write_playbook.cypher) | A4: a candidate playbook from a confirmed incident. Idempotent by id (derived from the decision), pinned ABOUT the root it was learned on, sourced to the incident. |

## Coordination: fenced leases, checkpoints, actions, handoffs

| Query | What it does |
|---|---|
| [`coord/queries/checkpoint.cypher`](../coord/queries/checkpoint.cypher) | Durable, idempotent checkpoint for step n. Written BEFORE the next step starts. |
| [`coord/queries/claim.cypher`](../coord/queries/claim.cypher) | Claim the oldest claimable task of a type and start a new fencing epoch. Lease time comes from the database clock, never from the worker. |
| [`coord/queries/complete.cypher`](../coord/queries/complete.cypher) | Close a task this worker holds, with no follow-up task. |
| [`coord/queries/create_task.cypher`](../coord/queries/create_task.cypher) | Create a task for an incident. Idempotent by task id. Tasks MUST start with epoch 0 and attempts 0: null + 1 is null, which would make every fenced write fail silently. |
| [`coord/queries/handoff.cypher`](../coord/queries/handoff.cypher) | Close this task and open the next one. The next id is derived, so a retry finds the same task instead of creating a second one. |
| [`coord/queries/heartbeat.cypher`](../coord/queries/heartbeat.cypher) | Extend the lease, only if this worker still holds it (full fence guard). |
| [`coord/queries/read_action.cypher`](../coord/queries/read_action.cypher) | Read an action by its intent key (who it went to, and whether it was sent). |
| [`coord/queries/read_checkpoints.cypher`](../coord/queries/read_checkpoints.cypher) | Work done so far on a task, in order. A taking-over worker reads this first. |
| [`coord/queries/read_task.cypher`](../coord/queries/read_task.cypher) | Used after a fenced write returns no rows, to tell already_done from lease_lost. |
| [`coord/queries/send_action.cypher`](../coord/queries/send_action.cypher) | Send a notification once per logical intent (e.g. 'inc-104:initial-notification'). Recipient, channel and payload are fixed on first write and reused on retry. before = 'pending' -> sent now (ok); before = 'sent' -> already_done. |
| [`coord/queries/stuck_sweep.cypher`](../coord/queries/stuck_sweep.cypher) | Tasks whose lease expired after the last allowed attempt are flagged for a human. |

## Agents: triage, decisions, confirmation

| Query | What it does |
|---|---|
| [`agents/queries/confirm.cypher`](../agents/queries/confirm.cypher) | The engineer confirmed the diagnosis. One write: record the feedback, mark the incident resolved, close the respond task and queue learning. The Learn task id is derived from the decision, so a crash before learning runs loses nothing. |
| [`agents/queries/decision_usage.cypher`](../agents/queries/decision_usage.cypher) | Learner: the memories a decision used, with whether each was applied and its verdict. |
| [`agents/queries/incident_context.cypher`](../agents/queries/incident_context.cypher) | Investigator: the incident behind a task, its alerting services and alert texts. |
| [`agents/queries/incident_memory.cypher`](../agents/queries/incident_memory.cypher) | Memory Lens, in brief: every memory the incident's decision considered. |
| [`agents/queries/incident_outcome.cypher`](../agents/queries/incident_outcome.cypher) | Report: an incident's status, diagnosis, verdict and who was notified. |
| [`agents/queries/incident_report.cypher`](../agents/queries/incident_report.cypher) | The G1 pass check: every task on the incident with its checkpoints and actions. |
| [`agents/queries/learn_context.cypher`](../agents/queries/learn_context.cypher) | Everything the learner needs: the decision, its verdict, and the root's kind. |
| [`agents/queries/open_incident.cypher`](../agents/queries/open_incident.cypher) | Triage: one Incident per alert group, idempotent by key. observed_at is the scenario time every worker uses for this incident. |
| [`agents/queries/record_decision.cypher`](../agents/queries/record_decision.cypher) | The investigator's root-cause decision. Immutable once written. |
| [`agents/queries/record_recall.cypher`](../agents/queries/record_recall.cypher) | What recall returned, written before any of it is checked, so the Memory Lens can show it while the investigation runs. Fenced like every task write. |
| [`agents/queries/record_usage.cypher`](../agents/queries/record_usage.cypher) | Which memories the decision considered, with the evidence for or against each. One USED edge per (memory, target) tried. The verdict is filled in later, once, by the learner (memory/queries/feedback.cypher). |
| [`agents/queries/reject.cypher`](../agents/queries/reject.cypher) | The engineer rejected the diagnosis. The incident goes to review, and a Learn task is still queued so any playbook that led the agent astray loses trust. |
| [`agents/queries/respond_context.cypher`](../agents/queries/respond_context.cypher) | Responder: the root-cause decision behind a respond task. |

## Conversation memory: the war room

| Query | What it does |
|---|---|
| [`chat/queries/add_message.cypher`](../chat/queries/add_message.cypher) | Messages are stored verbatim and keyed, so a retried write adds nothing. |
| [`chat/queries/incident_recap.cypher`](../chat/queries/incident_recap.cypher) | "Where did we leave <incident>?": the stored conversation with its outcome. |
| [`chat/queries/incident_steps.cypher`](../chat/queries/incident_steps.cypher) | Recap: how far the investigation got, and which workers did it. |
| [`chat/queries/open_session.cypher`](../chat/queries/open_session.cypher) | One war-room session per engineer per incident. |
| [`chat/queries/preferences_for.cypher`](../chat/queries/preferences_for.cypher) | A person's preferences that hold at scenario time for this kind of incident, with the message (and incident) each one came from. |
| [`chat/queries/recent_messages.cypher`](../chat/queries/recent_messages.cypher) | The engineer's recent conversations, newest first, so a new session can resume. |

## Agent tools (also served over MCP): multi-hop graph questions

| Query | What it does |
|---|---|
| [`tools/queries/blast_radius.cypher`](../tools/queries/blast_radius.cypher) | Everything that depends on a node, with distance and customer impact. |
| [`tools/queries/recent_changes.cypher`](../tools/queries/recent_changes.cypher) | Deploys and config changes to a service between $since and $now (scenario time), with who made them: a two-hop walk Person -> Change -> Service. |
| [`tools/queries/upstream_candidates.cypher`](../tools/queries/upstream_candidates.cypher) | Nodes the alerting services depend on (1-3 hops downstream), ranked by how many alerting services reach them, then by distance. |
| [`tools/queries/who_to_page.cypher`](../tools/queries/who_to_page.cypher) | Owner team and on-call engineer for a node, as they were at scenario time $at. |

## Simulated world: deploy history and org changes

| Query | What it does |
|---|---|
| [`sim/queries/close_on_call.cypher`](../sim/queries/close_on_call.cypher) | Org change: whoever is on call for a team stops being on call at $at. Validity is closed, never deleted, so who_to_page still answers for earlier times. |
| [`sim/queries/close_owner.cypher`](../sim/queries/close_owner.cypher) | Org change: a node's current owning team stops owning it at $at. |
| [`sim/queries/open_on_call.cypher`](../sim/queries/open_on_call.cypher) | Org change: a person goes on call for a team from $at (idempotent). |
| [`sim/queries/open_owner.cypher`](../sim/queries/open_owner.cypher) | Org change: a team owns a node from $at (idempotent). |
| [`sim/queries/record_change.cypher`](../sim/queries/record_change.cypher) | The world's deploy history: (:Person)-[:AUTHORED]->(:Change)-[:MODIFIED]->(:Service). Written by the simulator when a scenario starts, as a CI system would; nothing says which change (if any) caused an incident. Idempotent by key. |

## UI: what each panel reads

| Query | What it does |
|---|---|
| [`web/queries/actions.cypher`](../web/queries/actions.cypher) | Pager log: every action sent for the incident (there should be exactly one). |
| [`web/queries/checkpoints.cypher`](../web/queries/checkpoints.cypher) | Agent timeline: every checkpoint on the incident's tasks, with who wrote it and under which fencing epoch. |
| [`web/queries/facts.cypher`](../web/queries/facts.cypher) | What it remembers: every preference fact, every version, with the engineer's own words it came from. Superseded versions stay, closed by valid_to. |
| [`web/queries/graph_size.cypher`](../web/queries/graph_size.cypher) | Header chip: how big this company's graph is right now. |
| [`web/queries/held_investigations.cypher`](../web/queries/held_investigations.cypher) | Armed kill: investigations currently held under a lease, with how many steps their worker has checkpointed so far. |
| [`web/queries/incident_head.cypher`](../web/queries/incident_head.cypher) | UI: one incident with its alerts and, once made, the decision and the verdict. |
| [`web/queries/incidents.cypher`](../web/queries/incidents.cypher) | UI: the incident feed, newest first, with the diagnosis and whether memory solved it. |
| [`web/queries/last_observed.cypher`](../web/queries/last_observed.cypher) | Scenario clock: when the latest incident was observed (null on a fresh graph). |
| [`web/queries/lens.cypher`](../web/queries/lens.cypher) | Memory Lens: every memory the incident's decision considered, applied or not: why it was recalled (path, hops, score, trust at use), the evidence for and against it (checks_json), and what changed afterwards (verdict, trust after). |
| [`web/queries/mark_planted.cypher`](../web/queries/mark_planted.cypher) | The source of a deliberately wrong playbook is not a real incident; label it. |
| [`web/queries/messages.cypher`](../web/queries/messages.cypher) | War room: the conversation on an incident, in order. |
| [`web/queries/org.cypher`](../web/queries/org.cypher) | Who owns each node and who is on call for each team at scenario time $at. |
| [`web/queries/playbooks.cypher`](../web/queries/playbooks.cypher) | What it remembers: every playbook, where it is pinned and where it came from. |
| [`web/queries/root_count.cypher`](../web/queries/root_count.cypher) | How many earlier incidents were diagnosed and confirmed on this node, so a repeat failure gets alert wording it has not used before. |
| [`web/queries/service_map.cypher`](../web/queries/service_map.cypher) | The company's dependency graph, for the map panel. |
| [`web/queries/tasks.cypher`](../web/queries/tasks.cypher) | Agent timeline: the incident's tasks with their claims and current lease. lease_left_ms uses the database clock, the same clock the fence uses. |

## Evaluator only

| Query | What it does |
|---|---|
| [`eval/queries/incident_actions.cypher`](../eval/queries/incident_actions.cypher) | Evaluator: the notifications sent for an incident (who, how). |
| [`eval/queries/incident_usage.cypher`](../eval/queries/incident_usage.cypher) | Evaluator: every memory an incident's decision considered, with its family, so a scorer can tell a misleading memory from a rejected one. |
| [`eval/queries/memory_state.cypher`](../eval/queries/memory_state.cypher) | Evaluator: a memory's current counts and status (M5 retirement). |
