# agents/

| Module | Role |
| --- | --- |
| `contracts.py` | `Step`, `Call`, `Diagnosis`, `Verdict`, and the `Confirmer` protocol |
| `worker.py` | Claim → heartbeat thread → `handle()` → stop on `lease_lost` |
| `triage.py` | Alerts → `Incident` + `investigate` task. Deterministic, idempotent |
| `planning.py` | `RuleBasedPlanner`: a pure function of (alerting, history), so takeover resumes at the next step |
| `llm_planner.py` | `GuardedLLMPlanner`: the model proposes, the rule-based planner covers any invalid move |
| `investigator.py` | Recall → check playbooks against evidence → else plan; checkpoint every step; `Decision` + `USED` edges |
| `responder.py` | Owner at scenario time → preferences → one intent-keyed notification → war room → confirm/reject |
| `learner.py` | Per-memory verdicts and trust (A2); candidate playbooks from confirmed runs (A4) |

Every write goes through a fenced query and returns `ok`, `already_done` or `lease_lost`.
The investigator writes the `Decision` when it decides; the responder's confirmation
adds `Feedback`, resolves the incident and queues learning in one write.
