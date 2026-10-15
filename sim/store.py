"""The simulator shared between processes: one JSON file per active incident.

`SimulatedWorld` keeps scenarios in one process's memory, which is enough when all
workers run in that process. The UI runs investigators as separate processes (so
one can be killed for real), and they all need the same evidence. This store
writes each incident's hidden scenario to a directory outside the graph; any
process can rebuild the identical, deterministic `Evidence` from it.

The scenario (root, family) never goes into FalkorDB: agents only ever see the
evidence tools' answers.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict
from pathlib import Path

from sim.families import Evidence, Scenario


def _filename(incident_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", incident_key) + ".json"


class ScenarioStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, tuple[Scenario, Evidence]] = {}
        self._lock = threading.Lock()

    def start(self, incident_key: str, scenario: Scenario) -> list[dict]:
        """Begin a scenario under an incident key; return the alerts it fires."""
        raw = {**asdict(scenario), "alerting": list(scenario.alerting)}
        path = self.root / _filename(incident_key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw), encoding="utf-8")
        tmp.replace(path)  # atomic: a reader never sees half a file
        evidence = Evidence(scenario)
        with self._lock:
            self._cache[incident_key] = (scenario, evidence)
        return evidence.alerts()

    def _load(self, incident_key: str) -> tuple[Scenario, Evidence]:
        with self._lock:
            if incident_key in self._cache:
                return self._cache[incident_key]
        path = self.root / _filename(incident_key)
        if not path.exists():
            raise LookupError(f"no active scenario for {incident_key}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        scenario = Scenario(**{**raw, "alerting": tuple(raw["alerting"])})
        loaded = (scenario, Evidence(scenario))
        with self._lock:
            self._cache[incident_key] = loaded
        return loaded

    def evidence_for(self, incident_key: str) -> Evidence:
        return self._load(incident_key)[1]

    def observed_at(self, incident_key: str) -> int:
        return self._load(incident_key)[0].now_ms

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
        for path in self.root.glob("*.json"):
            path.unlink()
