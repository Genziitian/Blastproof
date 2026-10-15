"""Graph tools: multi-hop questions answered by Cypher on the company graph."""
from __future__ import annotations

from typing import Any

from common.db import run
from tools.context import ToolContext

Q = "tools/queries/"


def find_upstream_candidates(ctx: ToolContext, alerting: list[str]) -> list[dict[str, Any]]:
    return run(ctx.graph, Q + "upstream_candidates.cypher", {"alerting": alerting})


def blast_radius(ctx: ToolContext, node: str) -> list[dict[str, Any]]:
    return run(ctx.graph, Q + "blast_radius.cypher", {"node": node})


def who_to_page(ctx: ToolContext, node: str) -> dict[str, Any] | None:
    rows = run(ctx.graph, Q + "who_to_page.cypher", {"node": node, "at": ctx.scenario_now})
    return rows[0] if rows else None
