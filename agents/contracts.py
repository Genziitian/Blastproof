"""Data passed between agents, the planner and the confirmer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Step:
    """One completed tool call, as stored in a checkpoint."""

    n: int
    tool: str
    args: dict[str, Any]
    observation: Any


@dataclass(frozen=True)
class Call:
    """The planner's next move: run this tool with these arguments."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Diagnosis:
    root: str
    family: str
    summary: str
    evidence_steps: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "family": self.family,
            "summary": self.summary,
            "evidence_steps": list(self.evidence_steps),
        }


@dataclass(frozen=True)
class Verdict:
    confirmed: bool
    by: str
    message: str | None = None   # anything the engineer says in the war room


class Confirmer(Protocol):
    """Whoever approves a diagnosis: the on-call engineer, or the oracle in eval runs."""

    def review(self, incident_key: str, diagnosis: Diagnosis) -> Verdict: ...
