"""Pure-Python reference answers for graph queries, computed from sim.world.

Offline tests use these in place of FalkorDB; the live tests check that the Cypher
returns the same thing, so the two can't drift apart unnoticed.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from sim import world as W


def _downstream_hops(start: str, max_hops: int) -> dict[str, int]:
    edges: dict[str, list[str]] = {}
    for a, b in W.DEPENDS_ON:
        edges.setdefault(a, []).append(b)
    best: dict[str, int] = {}
    queue = deque([(start, 0)])
    while queue:
        node, d = queue.popleft()
        if d == max_hops:
            continue
        for nxt in edges.get(node, []):
            if nxt not in best or d + 1 < best[nxt]:
                best[nxt] = d + 1
                queue.append((nxt, d + 1))
    return best


def upstream_candidates(alerting: list[str]) -> list[dict[str, Any]]:
    """Same rows as tools/queries/upstream_candidates.cypher."""
    hits: dict[str, int] = {}
    hops: dict[str, int] = {}
    for a in set(alerting):
        for node, d in _downstream_hops(a, 3).items():
            hits[node] = hits.get(node, 0) + 1
            hops[node] = min(hops.get(node, d), d)
    rows = [
        {
            "name": n,
            "label": "Datastore" if n in W.DATASTORES else "Service",
            "kind": W.DATASTORES.get(n),
            "hits": hits[n],
            "hops": hops[n],
        }
        for n in hits
    ]
    return sorted(rows, key=lambda r: (-r["hits"], r["hops"], r["name"]))
