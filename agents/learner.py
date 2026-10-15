"""Learner: turns a reviewed incident into memory.

Claims `learn:<decision>` tasks queued by the responder's confirm or reject write:

1. Gives every memory the decision used its verdict (helped, misled or not
   applicable) and updates trust, at most once per memory per decision (A2).
2. If the diagnosis was confirmed and came from investigation rather than a
   recalled playbook, writes a candidate playbook from what the run observed (A4),
   or adds this incident as a source to an existing playbook with that signature.

Every write is idempotent, so a learner that dies part-way is simply retried.
"""
from __future__ import annotations

import json
from typing import Any

from agents.contracts import Step
from agents.worker import Worker
from common.db import run
from coord import tasks
from coord.tasks import Lease
from memory.feedback import verdicts
from memory.templates import candidate

Q = "memory/queries/"


class Learner(Worker):
    task_type = "learn"

    def handle(self, lease: Lease) -> None:
        rows = run(self.graph, "agents/queries/learn_context.cypher", {"task_id": lease.task_id})
        if not rows:
            raise LookupError(f"{lease.task_id}: no reviewed decision to learn from")
        c = rows[0]
        confirmed = c["verdict"] == "confirmed"

        usage = run(self.graph, "agents/queries/decision_usage.cypher",
                    {"decision_id": c["decision_id"]})
        updates = verdicts(usage, confirmed)
        if updates:
            for r in run(self.graph, Q + "feedback.cypher",
                         {"decision_id": c["decision_id"], "verdicts": updates}):
                self.log.info("%s -> %s: %s (trust now %.2f, %s)", r["id"], r["target"],
                              r["verdict"], r["trust"], r["status"])

        helped_by_memory = any(u["applied"] for u in usage)
        if confirmed and not helped_by_memory:
            self._learn_playbook(c)

        self.check_lease()
        self.require(tasks.complete(self.graph, lease))

    def _learn_playbook(self, c: dict[str, Any]) -> None:
        history = [Step(k["n"], k["tool"], json.loads(k["args_json"]),
                        json.loads(k["observation"])["result"])
                   for k in tasks.read_checkpoints(self.graph, c["investigate_task"])]
        playbook = candidate(c["family"], c["root"], c["root_kind"], history)
        if playbook is None:
            self.log.info("%s: no playbook; the run did not observe confirming evidence",
                          c["decision_id"])
            return

        existing = run(self.graph, Q + "playbook_by_signature.cypher",
                       {"signature": playbook.signature})
        if existing:
            run(self.graph, Q + "add_provenance.cypher",
                {"id": existing[0]["id"], "incident_key": c["incident_key"]})
            self.log.info("%s also supports %s", c["incident_key"], existing[0]["id"])
            return

        written = run(self.graph, Q + "write_playbook.cypher", {
            **playbook.fields(),
            "id": f"pb-{c['decision_id']}",
            "incident_key": c["incident_key"],
            "root": c["root"],
            "scenario_now": c["observed_at"],
        })
        if written:
            self.log.info("learned %s (%s) from %s", written[0]["id"], playbook.signature,
                          c["incident_key"])
