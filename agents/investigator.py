"""Investigator: works out the root cause of an incident from observable evidence.

1. Recall playbooks pinned near the alerting services (graph proximity, not text).
2. Check each recalled playbook's preconditions and steps against live evidence;
   the first that holds is the diagnosis.
3. Otherwise investigate with the planner. Steps already taken while checking
   playbooks count as evidence, so nothing is asked twice.

Every tool call is checkpointed before the next one starts. On takeover the
checkpoints are replayed, so the new worker continues instead of starting over.
"""
from __future__ import annotations

import json
import time
from typing import Any

from agents.contracts import Diagnosis, Step
from agents.planning import Planner, RuleBasedPlanner
from agents.worker import Worker
from common.db import run
from coord import tasks
from coord.tasks import Lease
from memory import recall
from memory.playbook import Observe
from memory.use import Consideration, try_playbooks
from tools import registry
from tools.context import EvidenceSource, ToolContext

MAX_STEPS = 12


def decision_id(incident_id: str) -> str:
    return f"dec-{incident_id}"


class Investigator(Worker):
    task_type = "investigate"

    def __init__(self, graph: Any, instance: str, evidence: EvidenceSource,
                 planner: Planner | None = None, use_memory: bool = True,
                 pace_s: float = 0.0) -> None:
        super().__init__(graph, instance)
        self.evidence = evidence
        self.planner = planner or RuleBasedPlanner()
        self.use_memory = use_memory
        self.pace_s = pace_s  # pause after each new step, so a live demo can be followed

    def handle(self, lease: Lease) -> None:
        incident = run(self.graph, "agents/queries/incident_context.cypher",
                       {"task_id": lease.task_id})[0]
        key, scenario_now = incident["incident_key"], incident["observed_at"]
        alerting: list[str] = incident["alerting"]
        ctx = ToolContext(self.graph, self.evidence.evidence_for(key), scenario_now)

        history = self._history(lease.task_id)
        if history:
            self.log.info("resuming %s from step %d", key, len(history) + 1)

        def observe(tool: str, args: dict[str, Any]) -> tuple[int, Any]:
            step = self._step(lease, ctx, history, tool, args)
            return step.n, step.observation

        considered: list[Consideration] = []
        diagnosis: Diagnosis | None = None
        if self.use_memory:
            recalled = recall.recall(self.graph, alerting, scenario_now)
            records = recall.playbooks(self.graph, (r.memory_id for r in recalled))
            considered, diagnosis = try_playbooks(recalled, records, observe)
            for c in considered:
                verdict = "applies" if c.applied else (
                    c.applicability.failed.description if c.applicability and c.applicability.failed
                    else c.note)
                self.log.info("recalled %s -> %s: %s", c.signature, c.recalled.target, verdict)

        if diagnosis is None:
            diagnosis = self._plan(alerting, history, observe)
        self.log.info("%s: %s (%s)", key, diagnosis.root, diagnosis.family)

        decision = decision_id(incident["incident_id"])
        self.require(self._record(lease, decision, diagnosis, scenario_now))
        if considered:
            self._record_usage(lease, decision, considered)
        self.require(tasks.handoff(self.graph, lease, "respond"))

    def _plan(self, alerting: list[str], history: list[Step], observe: Observe) -> Diagnosis:
        while len(history) < MAX_STEPS:
            move = self.planner.next(alerting, history)
            if isinstance(move, Diagnosis):
                return move
            observe(move.tool, move.args)
        return Diagnosis("unknown", "unknown", f"no conclusion within {MAX_STEPS} steps")

    def _step(self, lease: Lease, ctx: ToolContext, history: list[Step], tool: str,
              args: dict[str, Any]) -> Step:
        """Reuse an identical earlier step, or run the tool and checkpoint it."""
        for step in history:
            if step.tool == tool and step.args == args:
                return step
        self.check_lease()
        result = registry.call(ctx, tool, args)
        step = Step(len(history) + 1, tool, args, result.result)
        self.require(tasks.checkpoint(self.graph, lease, step.n, step.tool, step.args,
                                      result.observation_json(), ctx.scenario_now))
        self.log.info("step %d: %s %s", step.n, step.tool, json.dumps(step.args))
        history.append(step)
        if self.pace_s:
            time.sleep(self.pace_s)
        return step

    def _history(self, task_id: str) -> list[Step]:
        return [
            Step(c["n"], c["tool"], json.loads(c["args_json"]),
                 json.loads(c["observation"])["result"])
            for c in tasks.read_checkpoints(self.graph, task_id)
        ]

    def _record(self, lease: Lease, decision: str, diagnosis: Diagnosis,
                scenario_now: int) -> tasks.Result:
        rows = run(self.graph, "agents/queries/record_decision.cypher", {
            "task_id": lease.task_id, "epoch": lease.epoch, "instance": lease.instance,
            "decision_id": decision, "root": diagnosis.root,
            "family": diagnosis.family, "summary": diagnosis.summary,
            "evidence_steps": list(diagnosis.evidence_steps), "scenario_now": scenario_now,
        })
        if not rows:
            return tasks.Result(tasks.Outcome.LEASE_LOST)
        return tasks.Result(tasks.Outcome.OK, rows[0])

    def _record_usage(self, lease: Lease, decision: str,
                      considered: list[Consideration]) -> None:
        rows = run(self.graph, "agents/queries/record_usage.cypher", {
            "task_id": lease.task_id, "epoch": lease.epoch, "instance": lease.instance,
            "decision_id": decision, "used": [c.usage() for c in considered],
        })
        if not rows:
            self.require(tasks.Result(tasks.Outcome.LEASE_LOST))
