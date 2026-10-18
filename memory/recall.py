"""Graph-native recall (plan, A1 and A1b).

Memories are found by where they are pinned in the system, not by what words they
contain. Each candidate is a (memory, target) pair: one playbook learned on
postgres-orders can be tried against postgres-payments through a kind match.

    score = trust * age_decay * sum over alerting services of weight * 0.5 ** hops
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from common.db import run

Q = "memory/queries/"
DAY_MS = 86_400_000
# Recency weight e^(-age / 30 days): a memory's weight halves about every 21 days.
DECAY_DAYS = 30.0
TOP_K = 5
# One playbook can be pinned to many nodes (a bad-deploy playbook learned on four
# services). Without a cap its targets crowd every other memory out of the top K.
MAX_TARGETS_PER_MEMORY = 2


@dataclass(frozen=True)
class Recalled:
    memory_id: str
    target: str
    score: float
    trust: float
    hops: int
    path: tuple[str, ...]
    via_kind: bool

    def why(self) -> str:
        route = " -> ".join(self.path)
        how = "same kind of datastore" if self.via_kind else f"{self.hops} hop(s)"
        return f"{route} ({how}, trust {self.trust:.2f})"


def rank(rows: Iterable[Mapping[str, Any]], scenario_now: int, k: int = TOP_K) -> list[Recalled]:
    """Score candidate rows from the recall queries. Pure: no database access."""
    best: dict[tuple[str, str], dict[str, tuple[float, Mapping[str, Any]]]] = {}
    for row in rows:
        contribution = float(row["weight"]) * 0.5 ** int(row["hops"])
        per_alerting = best.setdefault((row["id"], row["target"]), {})
        current = per_alerting.get(row["alerting"])
        # Equal contributions (two 2-hop routes to the same node) are broken by the
        # path itself, so the binding never depends on the order the database returns.
        if current is None or contribution > current[0] or (
                contribution == current[0] and list(row["path"]) < list(current[1]["path"])):
            per_alerting[row["alerting"]] = (contribution, row)

    ranked = []
    for (memory_id, target), per_alerting in best.items():
        # The path used for binding: strongest contribution, ties broken by name.
        _, top = min(per_alerting.values(), key=lambda cr: (-cr[0], cr[1]["alerting"]))
        age_days = max(0.0, (scenario_now - int(top["recorded_at"])) / DAY_MS)
        decay = math.exp(-age_days / DECAY_DAYS)
        score = float(top["trust"]) * decay * sum(c for c, _ in per_alerting.values())
        ranked.append(Recalled(memory_id, target, round(score, 6), float(top["trust"]),
                               int(top["hops"]), tuple(top["path"]), float(top["weight"]) < 1.0))
    ranked.sort(key=lambda r: (-r.score, r.memory_id, r.target))
    kept: list[Recalled] = []
    per_memory: dict[str, int] = {}
    for r in ranked:
        if per_memory.get(r.memory_id, 0) < MAX_TARGETS_PER_MEMORY:
            per_memory[r.memory_id] = per_memory.get(r.memory_id, 0) + 1
            kept.append(r)
    return kept[:k]


def recall(graph: Any, alerting: list[str], scenario_now: int, k: int = TOP_K) -> list[Recalled]:
    params = {"alerting": alerting, "scenario_now": scenario_now}
    rows: list[dict[str, Any]] = []
    for name in ("recall_direct", "recall", "recall_kind"):
        rows += run(graph, f"{Q}{name}.cypher", params)
    return rank(rows, scenario_now, k)


def playbooks(graph: Any, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    rows = run(graph, Q + "playbooks_by_id.cypher", {"ids": sorted(set(ids))})
    return {r["id"]: r for r in rows}
