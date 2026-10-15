"""Procedural memory: playbooks with machine-checkable preconditions and steps.

A playbook is parameterised (`$alerting`, `$caller`, `$target`) so one learned on
postgres-orders can be checked against postgres-payments. Checks are evaluated
deterministically, without a model: either the evidence matches or the playbook
does not apply. Stored in FalkorDB as JSON strings, because maps can't be
properties.
"""
from __future__ import annotations

import hashlib
import json
import operator
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

OPS: dict[str, Callable[[Any, Any], bool]] = {
    ">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "==": operator.eq,
}
PARAMS = ("alerting", "caller", "target")


class BindingError(ValueError):
    pass


def _resolve(value: Any, bindings: Mapping[str, str | None]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        bound = bindings.get(value[1:])
        if bound is None:
            raise BindingError(f"{value} is not bound")
        return bound
    return value


@dataclass(frozen=True)
class Check:
    tool: str
    args: dict[str, Any]
    measure: str        # "last:<metric>" | "deploys" | "healthy:$param"
    op: str
    value: Any

    def bound_args(self, bindings: Mapping[str, str | None]) -> dict[str, Any]:
        return {k: _resolve(v, bindings) for k, v in self.args.items()}

    def measure_of(self, observation: Any, bindings: Mapping[str, str | None]) -> Any:
        if self.measure.startswith("last:"):
            series = (observation or {}).get(self.measure[5:])
            return series[-1] if series else None
        if self.measure == "deploys":
            return sum(1 for c in observation or [] if c.get("kind") == "deploy")
        if self.measure.startswith("healthy:"):
            dep = _resolve(self.measure[8:], bindings)
            return next((d["healthy"] for d in observation or [] if d.get("dep") == dep), None)
        raise ValueError(f"unknown measure {self.measure!r}")

    def passes(self, observed: Any) -> bool:
        return observed is not None and OPS[self.op](observed, self.value)

    def describe(self, bindings: Mapping[str, str | None]) -> str:
        args = ", ".join(f"{v}" for v in self.bound_args(bindings).values())
        return f"{self.tool}({args}): {self.measure} {self.op} {self.value}"


@dataclass(frozen=True)
class Playbook:
    signature: str
    family: str
    applies_to_kind: str
    params: tuple[str, ...]
    preconditions: tuple[Check, ...]
    steps: tuple[Check, ...]
    conclusion: str = "$target"
    stop_if: str = "any precondition or expected observation fails"

    def fields(self) -> dict[str, Any]:
        """Properties for the Playbook node (JSON strings for nested parts)."""
        body = {
            "signature": self.signature,
            "family": self.family,
            "applies_to_kind": self.applies_to_kind,
            "params_json": json.dumps(list(self.params)),
            "preconditions_json": json.dumps([asdict(c) for c in self.preconditions], sort_keys=True),
            "steps_json": json.dumps([asdict(c) for c in self.steps], sort_keys=True),
            "conclusion": self.conclusion,
            "stop_if": self.stop_if,
        }
        body["payload_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
        return body

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> Playbook:
        return cls(
            signature=row["signature"],
            family=row["family"],
            applies_to_kind=row["applies_to_kind"],
            params=tuple(json.loads(row["params_json"])),
            preconditions=tuple(Check(**c) for c in json.loads(row["preconditions_json"])),
            steps=tuple(Check(**c) for c in json.loads(row["steps_json"])),
            conclusion=row["conclusion"],
            stop_if=row.get("stop_if") or cls.stop_if,
        )


@dataclass(frozen=True)
class CheckResult:
    phase: str          # "precondition" | "step"
    description: str
    observed: Any
    passed: bool
    step_n: int


@dataclass(frozen=True)
class Applicability:
    applies: bool
    results: tuple[CheckResult, ...]
    root: str | None = None
    failed: CheckResult | None = field(default=None)


Observe = Callable[[str, dict[str, Any]], tuple[int, Any]]
"""Runs (or replays) a tool call; returns (checkpoint number, observation)."""


def bind(path: list[str], target: str) -> dict[str, str | None]:
    """Bind playbook parameters from a recall path: alerting service -> ... -> target."""
    if not path:
        raise BindingError("empty recall path")
    return {
        "alerting": path[0],
        "caller": path[-2] if len(path) >= 2 else None,
        "target": target,
    }


def check_applies(playbook: Playbook, bindings: Mapping[str, str | None],
                  observe: Observe) -> Applicability:
    """Run preconditions, then steps; stop at the first check that fails."""
    results: list[CheckResult] = []
    for phase, checks in (("precondition", playbook.preconditions), ("step", playbook.steps)):
        for check in checks:
            n, observation = observe(check.tool, check.bound_args(bindings))
            observed = check.measure_of(observation, bindings)
            result = CheckResult(phase, check.describe(bindings), observed,
                                 check.passes(observed), n)
            results.append(result)
            if not result.passed:
                return Applicability(False, tuple(results), failed=result)
    return Applicability(True, tuple(results), root=_resolve(playbook.conclusion, bindings))
