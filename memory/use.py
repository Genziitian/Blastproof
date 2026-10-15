"""Try recalled playbooks against live evidence before investigating from scratch.

Each recalled (playbook, target) pair is bound from its recall path and checked;
the first one whose preconditions and steps all hold becomes the diagnosis. Every
pair tried is reported, applicable or not, so the decision record (and the Memory
Lens) shows what was recalled, why, and which evidence ruled it in or out.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from agents.contracts import Diagnosis
from memory.playbook import Applicability, BindingError, Observe, Playbook, bind, check_applies
from memory.recall import Recalled


@dataclass(frozen=True)
class Consideration:
    recalled: Recalled
    signature: str
    applicability: Applicability | None
    note: str = ""

    @property
    def applied(self) -> bool:
        return bool(self.applicability and self.applicability.applies)

    def usage(self) -> dict[str, Any]:
        """Properties for the USED edge from the decision to this memory."""
        checks = [asdict(r) for r in self.applicability.results] if self.applicability else []
        return {
            "id": self.recalled.memory_id,
            "target": self.recalled.target,
            "score": self.recalled.score,
            "hops": self.recalled.hops,
            "path": list(self.recalled.path),
            "trust": self.recalled.trust,
            "applied": self.applied,
            "checks_json": json.dumps({"note": self.note, "checks": checks}, default=str),
        }


def try_playbooks(recalled: Sequence[Recalled], records: Mapping[str, Mapping[str, Any]],
                  observe: Observe) -> tuple[list[Consideration], Diagnosis | None]:
    considered: list[Consideration] = []
    for r in recalled:
        record = records.get(r.memory_id)
        if record is None:
            continue
        playbook = Playbook.from_record(record)
        try:
            result = check_applies(playbook, bind(list(r.path), r.target), observe)
        except BindingError as e:
            considered.append(Consideration(r, playbook.signature, None, f"not bindable: {e}"))
            continue
        considered.append(Consideration(r, playbook.signature, result))
        if result.applies and result.root:
            evidence = "; ".join(f"{c.description} (observed {c.observed})" for c in result.results)
            summary = (f"Recalled {playbook.signature} via {r.why()}. "
                       f"All checks held: {evidence}")
            steps = tuple(c.step_n for c in result.results if c.phase == "step")
            return considered, Diagnosis(result.root, playbook.family, summary[:600], steps)
    return considered, None
