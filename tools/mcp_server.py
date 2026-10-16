"""Serve the tool registry over MCP (stdio).

Starts one scenario in the simulator and exposes the same tools the agents use, so
any MCP client (Claude Desktop, the MCP Inspector) can investigate it by hand:

    python -m tools.mcp_server --company a --scenario s01

The schemas come from tools.registry, so the agents and MCP clients see one contract.
"""
from __future__ import annotations

import argparse
import asyncio

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from common.db import graph
from eval import truth
from sim import deploys
from sim.runtime import SimulatedWorld
from tools.registry import TOOLS, ToolContext, ToolError, call


def build_server(ctx: ToolContext) -> Server:
    server: Server = Server("blast-radius")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=t.name, description=t.description,
                       inputSchema=t.schema()["input_schema"])
            for t in TOOLS.values()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        try:
            text = call(ctx, name, arguments or {}).observation_json()
        except ToolError as e:
            text = f"error: {e}"
        return [types.TextContent(type="text", text=text)]

    return server


async def serve(ctx: ToolContext) -> None:
    server = build_server(ctx)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--company", required=True)
    ap.add_argument("--scenario", required=True)
    args = ap.parse_args()

    world = SimulatedWorld()
    incident_key = f"incident:mcp-{args.scenario}"
    scenario = truth.load(args.scenario).scenario()
    world.start(incident_key, scenario)
    deploys.publish(graph(args.company), incident_key, scenario)
    ctx = ToolContext(graph(args.company), world.evidence_for(incident_key),
                      world.observed_at(incident_key))
    asyncio.run(serve(ctx))


if __name__ == "__main__":
    main()
