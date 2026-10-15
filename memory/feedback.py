"""Per-memory verdicts (plan, A2).

Only a memory the agent actually followed can be credited or blamed. A playbook
ruled out by its own preconditions was "not applicable": that is the memory
working correctly, so its trust does not change.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

PRIORS = {"agent": (1, 1), "human": (2, 1)}


def verdicts(usage: Iterable[Mapping[str, Any]], confirmed: bool) -> list[dict[str, str]]:
    out = []
    for u in usage:
        if u.get("verdict") is not None:
            continue
        followed = "helped" if confirmed else "misled"
        out.append({"id": u["id"], "target": u["target"],
                    "verdict": followed if u["applied"] else "not_applicable"})
    return out


def trust(helped: int, misled: int, source: str = "agent") -> float:
    a, b = PRIORS[source]
    return (helped + a) / (helped + misled + a + b)


def retired(helped: int, misled: int, source: str = "agent") -> bool:
    return misled >= 2 and trust(helped, misled, source) < 0.5
