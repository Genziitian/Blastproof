"""How the investigator decides its next step.

A planner is a pure function of the alerting services and the steps already
taken. Because the steps come from durable checkpoints, a worker that takes over
a task asks the same question and gets the next step, not the first one.

`RuleBasedPlanner` is the deterministic baseline used for G1 and as a fallback.
An LLM planner implements the same protocol (G2).
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

from agents.contracts import Call, Diagnosis, Step
from common.signals import CACHE_COLLAPSED_PCT, DEPLOY_ERROR_PCT, SATURATED_PCT

MAX_DATASTORES = 3


class Planner(Protocol):
    def next(self, alerting: Sequence[str], history: Sequence[Step]) -> Call | Diagnosis: ...


def _key(tool: str, args: dict[str, Any]) -> str:
    return tool + json.dumps(args, sort_keys=True)


def _last(series: Sequence[float] | None) -> float | None:
    return series[-1] if series else None


class RuleBasedPlanner:
    """Shared dependencies, then recent changes, then datastore health, then any
    suspect deploy's error rate."""

    def next(self, alerting: Sequence[str], history: Sequence[Step]) -> Call | Diagnosis:
        done = {_key(s.tool, s.args) for s in history}
        for call in self._plan(sorted(alerting), history):
            if _key(call.tool, call.args) not in done:
                return call
        return self._conclude(history)

    def _plan(self, alerting: list[str], history: Sequence[Step]) -> list[Call]:
        calls = [Call("find_upstream_candidates", {"alerting": alerting})]
        candidates = next((s.observation for s in history
                           if s.tool == "find_upstream_candidates"), None)
        if candidates is None:
            return calls
        calls += [Call("inspect_recent_changes", {"service": s}) for s in alerting]
        calls += [Call("inspect_metrics", {"node": name})
                  for name in _shared_datastores(candidates)]
        deploy = _latest_deploy(history)
        if deploy and _datastore_finding(history) is None:
            calls.append(Call("inspect_metrics", {"node": deploy[1]}))
        return calls

    def _conclude(self, history: Sequence[Step]) -> Diagnosis:
        finding = _datastore_finding(history)
        if finding is not None:
            return finding
        deploy = _latest_deploy(history)
        if deploy is not None:
            _, service, change_step = deploy
            errors = next(((s.n, _last(s.observation.get("error_rate_pct")))
                           for s in history
                           if s.tool == "inspect_metrics" and s.args["node"] == service), None)
            if errors and errors[1] is not None and errors[1] >= DEPLOY_ERROR_PCT:
                return Diagnosis(service, "bad_deploy",
                                 f"{service} was deployed just before the alerts and its "
                                 f"error rate is {errors[1]:.0f}%", (change_step, errors[0]))
        return Diagnosis("unknown", "unknown", "no conclusive evidence", ())


def _datastore_finding(history: Sequence[Step]) -> Diagnosis | None:
    for step in history:
        if step.tool != "inspect_metrics":
            continue
        node, metrics = step.args["node"], step.observation
        connections = _last(metrics.get("db_connections_pct"))
        if connections is not None and connections >= SATURATED_PCT:
            return Diagnosis(node, "db_saturation",
                             f"{node} is using {connections:.0f}% of its connections", (step.n,))
        hit_rate = _last(metrics.get("cache_hit_rate_pct"))
        if hit_rate is not None and hit_rate < CACHE_COLLAPSED_PCT:
            return Diagnosis(node, "cache_failure",
                             f"{node} hit rate fell to {hit_rate:.0f}%", (step.n,))
    return None


def _latest_deploy(history: Sequence[Step]) -> tuple[int, str, int] | None:
    deploys = [(change["at_ms"], step.args["service"], step.n)
               for step in history if step.tool == "inspect_recent_changes"
               for change in step.observation if change.get("kind") == "deploy"]
    return max(deploys) if deploys else None


def _shared_datastores(candidates: list[dict[str, Any]]) -> list[str]:
    stores = [c for c in candidates if c.get("label") == "Datastore"]
    if not stores:
        return []
    most = max(c["hits"] for c in stores)
    ranked = sorted((c for c in stores if c["hits"] == most), key=lambda c: (c["hops"], c["name"]))
    return [c["name"] for c in ranked[:MAX_DATASTORES]]
