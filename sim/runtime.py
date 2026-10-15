"""The simulated outside world for running incidents.

It knows each active scenario but hands the tool layer only an `Evidence` object.
G1 runs every worker in one process, so this lives in memory; G2 moves it behind
a small HTTP service so separate worker containers can reach it.
"""
from __future__ import annotations

from sim.families import Evidence, Scenario


class SimulatedWorld:
    def __init__(self) -> None:
        self._active: dict[str, tuple[Scenario, Evidence]] = {}

    def start(self, incident_key: str, scenario: Scenario) -> list[dict]:
        """Begin a scenario under an incident key; return the alerts it fires."""
        evidence = Evidence(scenario)
        self._active[incident_key] = (scenario, evidence)
        return evidence.alerts()

    def evidence_for(self, incident_key: str) -> Evidence:
        try:
            return self._active[incident_key][1]
        except KeyError:
            raise LookupError(f"no active scenario for {incident_key}") from None

    def observed_at(self, incident_key: str) -> int:
        """Scenario time at which the incident is being investigated."""
        return self._active[incident_key][0].now_ms
