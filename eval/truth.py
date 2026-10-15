"""Scenario answers. Evaluator-only: read by the simulator (which plays the world)
and the oracle (which plays the engineer). Agents and tools must never import this.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sim.families import Scenario

TRUTH_DIR = Path(__file__).resolve().parent / "truth"


@dataclass(frozen=True)
class Truth:
    id: str
    family: str
    root: str
    onset_ms: int
    wording: int
    expected_owner_team: str
    expected_recipient: str
    engineer_says: str | None = None

    def scenario(self) -> Scenario:
        return Scenario(self.id, self.family, self.root, self.onset_ms, wording=self.wording)


def _to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def load(scenario_id: str) -> Truth:
    raw = json.loads((TRUTH_DIR / f"{scenario_id}.json").read_text(encoding="utf-8"))
    return Truth(
        id=raw["id"],
        family=raw["family"],
        root=raw["root"],
        onset_ms=_to_ms(raw["onset"]),
        wording=raw.get("wording", 0),
        expected_owner_team=raw["expected_owner_team"],
        expected_recipient=raw["expected_recipient"],
        engineer_says=raw.get("engineer_says"),
    )


def all_ids() -> list[str]:
    return sorted(p.stem for p in TRUTH_DIR.glob("*.json"))
