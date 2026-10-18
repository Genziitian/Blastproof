"""Task coordination: claim, heartbeat, checkpoint, action, handoff.

Every call returns an Outcome so a successful retry never looks like a lost lease:
  ok            the fenced write happened now
  already_done  it happened earlier (retry after a lost response, or takeover)
  lease_lost    this worker no longer owns the task and must stop at once
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from enum import Enum

from common import config
from common.db import run

Q = "coord/queries/"

# Sends the intent key turned into already_done instead of a second notification,
# across all workers in this process (the load benchmark reports it).
absorbed_sends = 0
_absorbed_lock = threading.Lock()


def _absorbed(result: Result) -> Result:
    global absorbed_sends
    with _absorbed_lock:
        absorbed_sends += 1
    return result


class Outcome(str, Enum):
    OK = "ok"
    ALREADY_DONE = "already_done"
    LEASE_LOST = "lease_lost"
    NONE = "none"  # nothing to claim


@dataclass
class Lease:
    task_id: str
    epoch: int
    instance: str


@dataclass
class Result:
    outcome: Outcome
    data: dict = field(default_factory=dict)


def create_task(g, task_id: str, task_type: str, incident_key: str) -> Result:
    rows = run(g, Q + "create_task.cypher",
               {"task_id": task_id, "type": task_type, "incident_key": incident_key})
    if not rows:
        raise LookupError(f"incident {incident_key!r} not found; task not created")
    return Result(Outcome.OK, rows[0])


def claim(g, task_type: str, instance: str) -> tuple[Result, Lease | None]:
    rows = run(g, Q + "claim.cypher", {
        "type": task_type, "instance": instance,
        "ttl_ms": config.LEASE_TTL_MS, "max_attempts": config.MAX_ATTEMPTS})
    if not rows:
        return Result(Outcome.NONE), None
    r = rows[0]
    return Result(Outcome.OK, r), Lease(r["id"], r["epoch"], instance)


def _guard_params(lease: Lease) -> dict:
    return {"task_id": lease.task_id, "epoch": lease.epoch, "instance": lease.instance}


def heartbeat(g, lease: Lease) -> Result:
    rows = run(g, Q + "heartbeat.cypher", {**_guard_params(lease), "ttl_ms": config.LEASE_TTL_MS})
    return Result(Outcome.OK, rows[0]) if rows else Result(Outcome.LEASE_LOST)


def checkpoint(g, lease: Lease, n: int, tool: str, args: dict, observation: str,
               scenario_now: int) -> Result:
    rows = run(g, Q + "checkpoint.cypher", {
        **_guard_params(lease), "cid": f"{lease.task_id}:{n}", "n": n, "tool": tool,
        "args_json": json.dumps(args, sort_keys=True), "observation": observation,
        "scenario_now": scenario_now})
    if not rows:
        return Result(Outcome.LEASE_LOST)
    r = rows[0]
    # A checkpoint written by an earlier epoch already existed: keep it, report it.
    return Result(Outcome.OK if r["written_by_epoch"] == lease.epoch else Outcome.ALREADY_DONE, r)


def read_checkpoints(g, task_id: str) -> list[dict]:
    return run(g, Q + "read_checkpoints.cypher", {"task_id": task_id})


def send_action(g, lease: Lease, intent_key: str, kind: str, recipient: str,
                channel: str, payload: dict) -> Result:
    rows = run(g, Q + "send_action.cypher", {
        **_guard_params(lease), "intent_key": intent_key, "kind": kind,
        "recipient": recipient, "channel": channel,
        "payload_json": json.dumps(payload, sort_keys=True)})
    if rows:
        r = rows[0]
        if r["before"] == "pending":
            return Result(Outcome.OK, r)
        return _absorbed(Result(Outcome.ALREADY_DONE, r))
    existing = run(g, Q + "read_action.cypher", {"intent_key": intent_key})
    if existing and existing[0]["status"] == "sent":
        return _absorbed(Result(Outcome.ALREADY_DONE, existing[0]))
    return Result(Outcome.LEASE_LOST)


def handoff(g, lease: Lease, next_type: str) -> Result:
    rows = run(g, Q + "handoff.cypher", {**_guard_params(lease), "next_type": next_type})
    if rows:
        return Result(Outcome.OK, rows[0])
    t = run(g, Q + "read_task.cypher", {"task_id": lease.task_id})
    if t and t[0]["status"] == "done" and t[0]["next_id"]:
        return Result(Outcome.ALREADY_DONE, {"next_id": t[0]["next_id"]})
    return Result(Outcome.LEASE_LOST, t[0] if t else {})


def complete(g, lease: Lease) -> Result:
    rows = run(g, Q + "complete.cypher", _guard_params(lease))
    if rows:
        return Result(Outcome.OK, rows[0])
    t = run(g, Q + "read_task.cypher", {"task_id": lease.task_id})
    if t and t[0]["status"] == "done":
        return Result(Outcome.ALREADY_DONE)
    return Result(Outcome.LEASE_LOST)


def stuck_sweep(g) -> list[str]:
    return [r["id"] for r in run(g, Q + "stuck_sweep.cypher",
                                 {"max_attempts": config.MAX_ATTEMPTS})]
