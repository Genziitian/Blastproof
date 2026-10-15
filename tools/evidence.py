"""Observation tools backed by the simulator. Read-only."""
from __future__ import annotations

from typing import Any

from tools.context import ToolContext


def inspect_metrics(ctx: ToolContext, node: str, window_min: int = 30) -> dict[str, Any]:
    return ctx.require_evidence().inspect_metrics(node, window_min)


def inspect_logs(ctx: ToolContext, node: str, n: int = 6) -> list[str]:
    return ctx.require_evidence().inspect_logs(node, n)


def inspect_recent_changes(ctx: ToolContext, service: str, hours: int = 2) -> list[dict[str, Any]]:
    return ctx.require_evidence().inspect_recent_changes(service, hours)


def check_dependency_health(ctx: ToolContext, service: str) -> list[dict[str, Any]]:
    return ctx.require_evidence().check_dependency_health(service)
