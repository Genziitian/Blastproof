"""M7: directly measure rejected stale writes after a lease takeover.

    python -m bench.fencing

Uses a fresh scratch graph, never a company graph. No model is called.
"""
from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from typing import Any

from bench.artifacts import save
from common.db import raw_graph
from coord import tasks
from coord.tasks import Outcome


def check(make_graph: Callable[[str], Any]) -> dict[str, Any]:
    g = make_graph(f"bench_fencing_{uuid.uuid4().hex[:10]}")
    key, task = "incident:t1", "t1:investigate"
    g.query("CREATE (:Incident {key: 'incident:t1', status: 'open'})")
    tasks.create_task(g, task, "investigate", key)
    _, old = tasks.claim(g, "investigate", "old-worker")
    assert old is not None
    tasks.checkpoint(g, old, 1, "inspect_metrics", {}, "{}", 0)
    g.query("MATCH (t:Task {id: $id}) SET t.lease_until = timestamp() - 1", {"id": task})
    _, new = tasks.claim(g, "investigate", "replacement")
    assert new is not None
    attempts = {
        "heartbeat": tasks.heartbeat(g, old).outcome.value,
        "checkpoint": tasks.checkpoint(g, old, 2, "stale", {}, "{}", 0).outcome.value,
        "handoff": tasks.handoff(g, old, "respond").outcome.value,
        "complete": tasks.complete(g, old).outcome.value,
        "action": tasks.send_action(g, old, "stale-action", "page", "priya", "page", {}).outcome.value,
    }
    preserved = [c["n"] for c in tasks.read_checkpoints(g, task)] == [1]
    resumed = tasks.checkpoint(g, new, 2, "inspect_metrics", {}, "{}", 0).outcome == Outcome.OK
    rejected = sum(value == Outcome.LEASE_LOST.value for value in attempts.values())
    return {"ok": rejected == len(attempts) and preserved and resumed and new.epoch > old.epoch,
            "stale_writes_rejected": rejected, "stale_writes_attempted": len(attempts),
            "attempts": attempts, "checkpoint_preserved": preserved, "replacement_resumed": resumed,
            "old_epoch": old.epoch, "new_epoch": new.epoch}


def main() -> int:
    graphs = []
    def make_graph(name: str) -> Any:
        g = raw_graph(name)
        graphs.append(g)
        return g
    try:
        result = check(make_graph)
        path = save("fencing", result)
        print(json.dumps(result, indent=2))
        print(f"written to {path}")
        return 0 if result["ok"] else 1
    finally:
        for g in graphs:
            g.delete()


if __name__ == "__main__":
    sys.exit(main())
