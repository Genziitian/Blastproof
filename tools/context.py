from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sim.families import Evidence


class ToolError(ValueError):
    pass


class EvidenceSource(Protocol):
    """Where a worker gets observations for an incident (the simulator, in this project)."""

    def evidence_for(self, incident_key: str) -> Evidence: ...


@dataclass(frozen=True)
class ToolContext:
    """Trusted state a tool runs against, built by the worker, never by the model."""

    graph: Any
    evidence: Evidence | None
    scenario_now: int

    def require_evidence(self) -> Evidence:
        if self.evidence is None:
            raise ToolError("no evidence source attached to this context")
        return self.evidence
