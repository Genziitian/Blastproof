"""Publish a scenario's deploy history to the company graph.

Called by whatever plays the world (the incident runner, the UI, the benchmark)
right after a scenario starts. Agents then read deploys with a graph query
(tools/queries/recent_changes.cypher), as they would read a real CI history.
"""
from __future__ import annotations

from typing import Any

from common.db import run
from sim.families import Scenario, scenario_changes


def publish(graph: Any, incident_key: str, scenario: Scenario) -> int:
    incident_id = incident_key.removeprefix("incident:")
    written = 0
    for i, c in enumerate(scenario_changes(scenario)):
        written += len(run(graph, "sim/queries/record_change.cypher", {
            "key": f"change:{incident_id}:{i}", "service": c["service"], "author": c["author"],
            "kind": c["kind"], "at": c["at_ms"], "summary": c["summary"],
        }))
    return written
