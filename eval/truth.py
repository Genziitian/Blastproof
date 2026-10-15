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
class OrgEvent:
    """A change to the company applied just before an incident (eval category: org change)."""

    at_ms: int
    kind: str            # "on_call" (team, person) | "owner" (node, team)
    team: str
    person: str | None = None
    node: str | None = None


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
    category: str = ""
    expected_channel: str | None = None
    org_events: tuple[OrgEvent, ...] = ()

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
        category=raw.get("category", ""),
        expected_channel=raw.get("expected_channel"),
        org_events=tuple(OrgEvent(_to_ms(e["at"]), e["kind"], e["team"], e.get("person"),
                                  e.get("node")) for e in raw.get("org_events", [])),
    )


def all_ids() -> list[str]:
    return sorted(p.stem for p in TRUTH_DIR.glob("*.json"))


def story_ids() -> list[str]:
    """The hand-written demo scenarios (s01-s05), as opposed to the benchmark (e*, m5*).
    They assume the company as seeded: no org changes."""
    return [i for i in all_ids() if i.startswith("s")]
