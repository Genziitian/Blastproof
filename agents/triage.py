"""Triage: turn a group of alerts into an Incident and queue its investigation.

Deterministic and idempotent: replaying the same alerts changes nothing.
"""
from __future__ import annotations

from typing import Any

from common.db import run
from coord import tasks


def incident_key(incident_id: str) -> str:
    return f"incident:{incident_id}"


def open_incident(graph: Any, incident_id: str, alerts: list[dict[str, Any]],
                  observed_at: int) -> str:
    key = incident_key(incident_id)
    rows = [{**a, "key": f"alert:{incident_id}:{a['service']}"} for a in alerts]
    run(graph, "agents/queries/open_incident.cypher", {
        "incident_key": key, "incident_id": incident_id,
        "alerts": rows, "observed_at": observed_at,
    })
    tasks.create_task(graph, f"{key}:investigate", "investigate", key)
    return key
