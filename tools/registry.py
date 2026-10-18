"""The tools an agent may call, defined once.

The same registry backs the in-process agent loop and the MCP server. Every tool
receives a `ToolContext` built by the worker from trusted state (the company graph,
the incident's evidence, the scenario clock). The model only ever supplies the
arguments listed in each tool's schema, so it cannot pick another company's graph.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tools import evidence, topology
from tools.context import ToolContext, ToolError

__all__ = ["INVESTIGATOR_TOOLS", "TOOLS", "Tool", "ToolContext", "ToolError", "ToolResult", "call",
           "validate"]


@dataclass(frozen=True)
class ToolResult:
    tool: str
    args: dict[str, Any]
    result: Any
    source: str

    def observation_json(self) -> str:
        return json.dumps({"result": self.result, "source": self.source}, sort_keys=True)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, dict[str, Any]]
    run: Callable[..., Any]
    source: str
    required: tuple[str, ...] = field(default=())
    # False: served over MCP (and to people) but not offered to the investigator, so
    # adding an analysis tool never changes how the benchmark's agent behaves.
    investigator: bool = True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": list(self.required),
                "additionalProperties": False,
            },
        }


_STRING = {"type": "string"}
_SERVICE = {"type": "string", "description": "Service or datastore name, e.g. postgres-orders"}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "inspect_metrics",
            "Recent metrics for a service or datastore: latency and error rate for services; "
            "connection usage, cache hit rate or consumer lag for datastores.",
            {"node": _SERVICE, "window_min": {"type": "integer", "minimum": 5, "maximum": 120}},
            evidence.inspect_metrics,
            "simulator",
            required=("node",),
        ),
        Tool(
            "inspect_logs",
            "The most recent log lines from a service or datastore.",
            {"node": _SERVICE, "n": {"type": "integer", "minimum": 1, "maximum": 20}},
            evidence.inspect_logs,
            "simulator",
            required=("node",),
        ),
        Tool(
            "inspect_recent_changes",
            "Deploys and config changes to a service within the last few hours.",
            {"service": _SERVICE, "hours": {"type": "integer", "minimum": 1, "maximum": 48}},
            topology.inspect_recent_changes,
            "cypher:tools/queries/recent_changes.cypher",
            required=("service",),
        ),
        Tool(
            "check_dependency_health",
            "Health of each direct dependency of a service.",
            {"service": _SERVICE},
            evidence.check_dependency_health,
            "simulator",
            required=("service",),
        ),
        Tool(
            "find_upstream_candidates",
            "Nodes the alerting services depend on, ranked by how many of them share it.",
            {"alerting": {"type": "array", "items": _STRING, "minItems": 1}},
            topology.find_upstream_candidates,
            "cypher:tools/queries/upstream_candidates.cypher",
            required=("alerting",),
        ),
        Tool(
            "blast_radius",
            "Every service that depends on a node, with hop count and customer impact.",
            {"node": _SERVICE},
            topology.blast_radius,
            "cypher:tools/queries/blast_radius.cypher",
            required=("node",),
        ),
        Tool(
            "who_to_page",
            "Owner team and current on-call engineer for a node.",
            {"node": _SERVICE},
            topology.who_to_page,
            "cypher:tools/queries/who_to_page.cypher",
            required=("node",),
        ),
        Tool(
            "rank_suspects",
            "Where to look first: nodes the alerting services depend on, ranked by how many "
            "of them reach it, how close it is, then FalkorDB PageRank over DEPENDS_ON (how "
            "much of the system leans on it). A ranking, not a diagnosis: evidence decides.",
            {"alerting": {"type": "array", "items": _STRING, "minItems": 1}},
            topology.rank_suspects,
            "cypher:tools/queries/rank_suspects.cypher",
            required=("alerting",),
            investigator=False,
        ),
        Tool(
            "explain_path",
            "Why a node matters to these alerts: the shortest DEPENDS_ON path from each "
            "alerting service to it (FalkorDB algo.SPpaths, at most 4 hops).",
            {"alerting": {"type": "array", "items": _STRING, "minItems": 1}, "node": _SERVICE},
            topology.explain_path,
            "cypher:tools/queries/explain_path.cypher",
            required=("alerting", "node"),
            investigator=False,
        ),
    ]
}
# The tools the investigating agent may call (in-process and LLM-planned).
INVESTIGATOR_TOOLS: dict[str, Tool] = {n: t for n, t in TOOLS.items() if t.investigator}

_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "array": list,
}


def validate(tool: Tool, args: dict[str, Any]) -> None:
    unknown = set(args) - set(tool.parameters)
    if unknown:
        raise ToolError(f"{tool.name}: unknown argument(s) {sorted(unknown)}")
    missing = [r for r in tool.required if r not in args]
    if missing:
        raise ToolError(f"{tool.name}: missing argument(s) {missing}")
    for name, value in args.items():
        spec = tool.parameters[name]
        expected = _TYPES[spec["type"]]
        if not isinstance(value, expected) or isinstance(value, bool):
            raise ToolError(f"{tool.name}: {name} must be {spec['type']}")
        # The bounds the schema advertises are enforced too (a model asking for
        # hours=100000 or an empty alert list is told so, not obeyed).
        if "minimum" in spec and value < spec["minimum"]:
            raise ToolError(f"{tool.name}: {name} must be at least {spec['minimum']}")
        if "maximum" in spec and value > spec["maximum"]:
            raise ToolError(f"{tool.name}: {name} must be at most {spec['maximum']}")
        if "minItems" in spec and isinstance(value, list) and len(value) < spec["minItems"]:
            raise ToolError(f"{tool.name}: {name} needs at least {spec['minItems']} item(s)")
        item = spec.get("items", {}).get("type")
        if item and isinstance(value, list) and not all(isinstance(v, _TYPES[item]) for v in value):
            raise ToolError(f"{tool.name}: every {name} item must be {item}")


def call(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"unknown tool {name!r}")
    validate(tool, args)
    return ToolResult(name, args, tool.run(ctx, **args), tool.source)
