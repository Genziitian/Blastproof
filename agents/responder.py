"""Responder: notifies the right person the way they asked, then records their verdict.

- Who: the owner and on-call at scenario time (`who_to_page`).
- How: the engineer's saved preferences for this kind of incident (channel, raw
  logs or summary), each cited back to the message it came from.
- Once: the notification is keyed by intent (`<incident>:initial-notification`), so
  a retry or a takeover reuses the stored recipient instead of notifying again.
- Afterwards: anything the engineer says is stored verbatim; instructions become
  preferences after a read-back. Confirm or reject closes the task and queues
  learning in one write.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agents.contracts import Confirmer, Diagnosis, Verdict
from agents.worker import LeaseLost, Worker
from chat.preferences import readback
from chat.war_room import AppliedPreference, WarRoom
from common.db import run
from coord import tasks
from coord.tasks import Lease, Outcome
from tools import registry
from tools.context import EvidenceSource, ToolContext

DEFAULT_CHANNEL = "page"
RAW_LOG_LINES = 6
DIAGNOSIS_LABELS = {
    "db_saturation": "database saturation",
    "bad_deploy": "a bad deploy",
    "cache_failure": "a cache failure",
}


class Responder(Worker):
    task_type = "respond"

    def __init__(self, graph: Any, instance: str, confirmer: Confirmer,
                 evidence: EvidenceSource | None = None, war_room: WarRoom | None = None) -> None:
        super().__init__(graph, instance)
        self.confirmer = confirmer
        self.evidence = evidence
        self.war_room = war_room or WarRoom(graph)

    def handle(self, lease: Lease) -> None:
        rows = run(self.graph, "agents/queries/respond_context.cypher", {"task_id": lease.task_id})
        if not rows:
            raise LookupError(f"{lease.task_id}: no decision to respond to")
        c = rows[0]
        key, now = c["incident_key"], c["observed_at"]
        diagnosis = Diagnosis(c["root"], c["family"], c["summary"],
                              tuple(c["evidence_steps"] or ()))

        sent: tuple[str, str] | None = None
        if diagnosis.root != "unknown":
            sent = self._notify(lease, key, diagnosis, now)

        verdict = self.confirmer.review(key, diagnosis)
        self.log.info("%s: diagnosis %s by %s", key,
                      "confirmed" if verdict.confirmed else "rejected", verdict.by)
        if sent and verdict.message:
            self._converse(c["incident_id"], key, sent, verdict, now)
        self._close(lease, c["decision_id"], verdict, now)

    def _notify(self, lease: Lease, key: str, diagnosis: Diagnosis,
                now: int) -> tuple[str, str] | None:
        ctx = ToolContext(self.graph, self._evidence(key), now)
        owner = registry.call(ctx, "who_to_page", {"node": diagnosis.root}).result
        if not owner or not owner.get("on_call"):
            self.log.warning("%s: nobody on call for %s", key, diagnosis.root)
            return None
        handle = owner["on_call"]
        prefs = {p.predicate: p for p in self.war_room.preferences(handle, diagnosis.family, now)}
        channel_pref = prefs.get("preferred_channel")
        channel = channel_pref.value if channel_pref else DEFAULT_CHANNEL

        impacted = registry.call(ctx, "blast_radius", {"node": diagnosis.root}).result
        raw_lines: list[str] = []
        detail = prefs.get("wants_detail")
        if detail and detail.value == "raw_logs" and ctx.evidence is not None:
            raw_lines = registry.call(ctx, "inspect_logs",
                                      {"node": diagnosis.root, "n": RAW_LOG_LINES}).result

        text = _notification_text(diagnosis, impacted, raw_lines, list(prefs.values()))
        payload = {
            "incident": key, "root": diagnosis.root, "family": diagnosis.family,
            "customer_impact": [r["service"] for r in impacted if r.get("customer_facing")],
            "team": owner["team"], "text": text,
            "applied_preferences": _citations(prefs.values()),
        }
        self.check_lease()
        result = self.require(tasks.send_action(
            self.graph, lease, f"{key}:initial-notification", "notification",
            handle, channel, payload))
        sent_to: str = result.data.get("recipient") or handle
        via = result.data.get("channel")
        if result.outcome is Outcome.ALREADY_DONE:
            self.log.info("%s: %s was already notified via %s", key, sent_to, via)
        else:
            self.log.info("%s: notified %s via %s", key, sent_to, via)
        return sent_to, text

    def _converse(self, incident_id: str, key: str, sent: tuple[str, str], verdict: Verdict,
                  now: int) -> None:
        handle, notification = sent
        room = self.war_room
        session = room.open(incident_id, key, handle, now)
        room.say(session, 1, "agent", notification, now)
        said = room.say(session, 2, "engineer", verdict.message or "", now)
        prefs = room.understand(verdict.message or "")
        if not prefs:
            return
        room.say(session, 3, "agent", readback(prefs), now)
        room.remember(handle, said, prefs, approved_by=handle, scenario_now=now)
        self.log.info("%s: saved %d preference(s) from %s", key, len(prefs), handle)

    def _close(self, lease: Lease, decision_id: str, verdict: Verdict, now: int) -> None:
        params = {
            "task_id": lease.task_id, "epoch": lease.epoch, "instance": lease.instance,
            "decision_id": decision_id, "feedback_id": f"fb-{decision_id}", "by": verdict.by,
            "scenario_now": now, "learn_task_id": f"learn:{decision_id}",
        }
        query = "confirm.cypher" if verdict.confirmed else "reject.cypher"
        if run(self.graph, f"agents/queries/{query}", params):
            return
        task = run(self.graph, "coord/queries/read_task.cypher", {"task_id": lease.task_id})
        if not task or task[0]["status"] != "done":
            raise LeaseLost

    def _evidence(self, key: str) -> Any:
        if self.evidence is None:
            return None
        try:
            return self.evidence.evidence_for(key)
        except LookupError:
            return None


def _notification_text(diagnosis: Diagnosis, impacted: list[dict[str, Any]],
                       raw_lines: list[str], prefs: list[AppliedPreference]) -> str:
    label = DIAGNOSIS_LABELS.get(diagnosis.family, diagnosis.family)
    customers = [r["service"] for r in impacted if r.get("customer_facing")]
    lines = [f"{diagnosis.root}: likely {label}. {diagnosis.summary}"]
    if customers:
        lines.append(f"Customer impact: {', '.join(customers)}.")
    if raw_lines:
        lines.append("Raw lines:")
        lines += [f"  {line}" for line in raw_lines]
    lines += [f"Sent this way {c}" for c in _citations(prefs)]
    return "\n".join(lines)


def _citations(prefs: Iterable[AppliedPreference]) -> list[str]:
    """One citation per source message, however many preferences it gave."""
    return list(dict.fromkeys(p.citation() for p in prefs if p.learned_in))
