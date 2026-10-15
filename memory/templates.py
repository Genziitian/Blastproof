"""How a confirmed incident becomes a candidate playbook (plan, A4).

Each failure family has a template: the rule-outs to check first (preconditions)
and the observation that confirms it (steps). A candidate is only written if the
confirmed run actually observed that confirming evidence, so playbooks come from
what happened, not from the template alone.
"""
from __future__ import annotations

from collections.abc import Sequence

from agents.contracts import Step
from common.signals import CACHE_COLLAPSED_PCT, DEPLOY_ERROR_PCT, SATURATED_PCT
from memory.playbook import Check, Playbook

_NO_RECENT_DEPLOY = Check("inspect_recent_changes", {"service": "$alerting"}, "deploys", "==", 0)
_TARGET_UNHEALTHY = Check("check_dependency_health", {"service": "$caller"},
                          "healthy:$target", "==", False)


def _datastore(family: str, kind: str, confirm: Check) -> Playbook:
    return Playbook(
        signature=f"{family}:{kind}",
        family=family,
        applies_to_kind=kind,
        params=("alerting", "caller", "target"),
        preconditions=(_NO_RECENT_DEPLOY, _TARGET_UNHEALTHY),
        steps=(confirm,),
    )


def template(family: str, kind: str) -> Playbook | None:
    if family == "db_saturation":
        return _datastore(family, kind, Check(
            "inspect_metrics", {"node": "$target"}, "last:db_connections_pct", ">=", SATURATED_PCT))
    if family == "cache_failure":
        return _datastore(family, kind, Check(
            "inspect_metrics", {"node": "$target"}, "last:cache_hit_rate_pct", "<",
            CACHE_COLLAPSED_PCT))
    if family == "bad_deploy":
        return Playbook(
            signature="bad_deploy:service",
            family=family,
            applies_to_kind="service",
            params=("target",),
            preconditions=(),
            steps=(
                Check("inspect_recent_changes", {"service": "$target"}, "deploys", ">=", 1),
                Check("inspect_metrics", {"node": "$target"}, "last:error_rate_pct", ">=",
                      DEPLOY_ERROR_PCT),
            ),
        )
    return None


def candidate(family: str, root: str, root_kind: str, history: Sequence[Step]) -> Playbook | None:
    """The template for this family, if the run's own steps support every confirming check."""
    playbook = template(family, root_kind)
    if playbook is None:
        return None
    bindings = {"target": root}
    for check in playbook.steps:
        args = check.bound_args(bindings)
        seen = [s for s in history if s.tool == check.tool and s.args == args]
        if not seen or not check.passes(check.measure_of(seen[-1].observation, bindings)):
            return None
    return playbook
