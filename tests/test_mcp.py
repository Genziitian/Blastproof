"""The tools served over MCP: what an MCP client sees is what the agents use.

    python -m unittest tests.test_mcp -v

A real MCP client session talks to tools.mcp_server's server over an in-memory
transport: it lists the tools, then calls graph tools (multi-hop Cypher) and an
evidence tool. Runs on the graph double always, and on FalkorDB when reachable.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from mcp.shared.memory import create_connected_server_and_client_session

from eval import truth
from scripts.seed import seed_graph
from sim import deploys
from sim.families import Evidence
from tests.backends import SKIP_REASON, double, falkordb, falkordb_up
from tools.context import ToolContext
from tools.mcp_server import build_server
from tools.registry import TOOLS


class McpCases:
    backend: Any

    def test_client_lists_and_calls_the_agents_tools(self):
        g = self.backend("mcp_scratch")
        seed_graph(g, "a")
        sc = truth.load("s02").scenario()  # bad deploy on checkout-api
        deploys.publish(g, "incident:mcp-s02", sc)
        server = build_server(ToolContext(g, Evidence(sc), sc.now_ms))

        async def session() -> dict[str, Any]:
            async with create_connected_server_and_client_session(server) as client:
                listed = [t.name for t in (await client.list_tools()).tools]
                out: dict[str, Any] = {"tools": listed}
                for name, args in (("find_upstream_candidates", {"alerting": list(sc.alerting)}),
                                   ("blast_radius", {"node": "postgres-orders"}),
                                   ("inspect_recent_changes", {"service": "checkout-api"}),
                                   ("who_to_page", {"node": "checkout-api"}),
                                   ("inspect_metrics", {"node": "checkout-api"}),
                                   ("rank_suspects", {"alerting": list(sc.alerting)}),
                                   ("explain_path", {"alerting": ["web-gateway"],
                                                     "node": "postgres-orders"})):
                    res = await client.call_tool(name, args)
                    out[name] = json.loads(res.content[0].text)
                bad = await client.call_tool("blast_radius", {"node": "x", "graph": "company_b"})
                out["bad"] = (bad.isError, bad.content[0].text)
                return out

        out = asyncio.run(session())
        self.assertEqual(sorted(out["tools"]), sorted(TOOLS))
        self.assertTrue(out["find_upstream_candidates"]["source"].startswith("cypher:"))
        hops = {r["service"]: r["hops"] for r in out["blast_radius"]["result"]}
        self.assertEqual(hops["web-gateway"], 2)  # web-gateway -> cart-svc -> postgres-orders
        [change] = out["inspect_recent_changes"]["result"]
        self.assertEqual((change["kind"], change["author"]), ("deploy", "rohan"))
        self.assertEqual(out["who_to_page"]["result"]["on_call"], "rohan")
        self.assertEqual(out["inspect_metrics"]["source"], "simulator")
        # Graph algorithms as tools: PageRank breaks ties between equally reached nodes,
        # and the shortest path explains why a node matters to the alerts.
        suspects = out["rank_suspects"]["result"]
        self.assertTrue(all(isinstance(r["pagerank"], float) for r in suspects))
        self.assertEqual([(r["hits"], r["hops"]) for r in suspects],
                         sorted(((r["hits"], r["hops"]) for r in suspects),
                                key=lambda x: (-x[0], x[1])))
        [why] = out["explain_path"]["result"]
        self.assertEqual((why["path"][0], why["path"][-1], why["hops"]),
                         ("web-gateway", "postgres-orders", 2.0))
        is_error, text = out["bad"]  # the schema forbids extra arguments, such as a graph name
        self.assertTrue(is_error)
        self.assertIn("graph", text)


class McpOnDouble(McpCases, unittest.TestCase):
    backend = staticmethod(double)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class McpOnFalkorDB(McpCases, unittest.TestCase):
    backend = staticmethod(falkordb)


if __name__ == "__main__":
    unittest.main()
