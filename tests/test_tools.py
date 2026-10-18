"""Tool registry contract, offline: python -m unittest tests.test_tools -v"""
from __future__ import annotations

import json
import unittest

from eval import truth
from sim.families import Evidence
from tools.context import ToolContext, ToolError
from tools.registry import TOOLS, call, validate

FORBIDDEN_ARGS = {"graph", "company", "company_id", "tenant", "incident", "scenario", "truth"}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        sc = truth.load("s01").scenario()
        self.ctx = ToolContext(graph=None, evidence=Evidence(sc), scenario_now=sc.now_ms)

    def test_model_cannot_choose_tenant_or_scenario(self):
        for tool in TOOLS.values():
            with self.subTest(tool=tool.name):
                self.assertFalse(FORBIDDEN_ARGS & set(tool.parameters))

    def test_schemas_are_complete(self):
        for tool in TOOLS.values():
            with self.subTest(tool=tool.name):
                schema = tool.schema()["input_schema"]
                self.assertEqual(schema["type"], "object")
                self.assertFalse(schema["additionalProperties"])
                self.assertTrue(set(schema["required"]) <= set(schema["properties"]))
                self.assertTrue(tool.description.endswith("."))

    def test_analysis_tools_are_served_but_not_given_to_the_investigator(self):
        from tools.registry import INVESTIGATOR_TOOLS
        self.assertEqual({"rank_suspects", "explain_path"}, set(TOOLS) - set(INVESTIGATOR_TOOLS))
        self.assertTrue(all(TOOLS[n].source.startswith("cypher:")
                            for n in ("rank_suspects", "explain_path")))

    def test_rejects_bad_arguments(self):
        tool = TOOLS["inspect_metrics"]
        with self.assertRaises(ToolError):
            validate(tool, {})
        with self.assertRaises(ToolError):
            validate(tool, {"node": "x", "graph": "company_b"})
        with self.assertRaises(ToolError):
            validate(tool, {"node": 3})
        with self.assertRaises(ToolError):
            validate(tool, {"node": "x", "window_min": True})
        with self.assertRaises(ToolError):
            call(self.ctx, "drop_database", {})
        for name, args in (("inspect_metrics", {"node": "x", "window_min": 100000}),
                           ("inspect_logs", {"node": "x", "n": 0}),
                           ("find_upstream_candidates", {"alerting": []}),
                           ("find_upstream_candidates", {"alerting": ["ok", 3]})):
            with self.subTest(tool=name, args=args), self.assertRaises(ToolError):
                validate(TOOLS[name], args)

    def test_evidence_results_serialise(self):
        for name, args in [
            ("inspect_metrics", {"node": "postgres-orders"}),
            ("inspect_logs", {"node": "cart-svc"}),
            ("check_dependency_health", {"service": "cart-svc"}),
        ]:
            with self.subTest(tool=name):
                result = call(self.ctx, name, args)
                decoded = json.loads(result.observation_json())
                self.assertEqual(decoded["source"], "simulator")

    def test_recent_changes_come_from_the_graph(self):
        from scripts.seed import seed_graph
        from sim import deploys
        from tests.graph_double import GraphDouble
        g = GraphDouble()
        seed_graph(g, "a")
        sc = truth.load("s02").scenario()  # a bad deploy on checkout-api
        self.assertEqual(deploys.publish(g, "incident:s02-x", sc), 2)
        self.assertEqual(deploys.publish(g, "incident:s02-x", sc), 2)  # idempotent
        ctx = ToolContext(graph=g, evidence=Evidence(sc), scenario_now=sc.now_ms)
        got = call(ctx, "inspect_recent_changes", {"service": "checkout-api"})
        self.assertEqual(got.result, Evidence(sc).inspect_recent_changes("checkout-api"))
        self.assertEqual(json.loads(got.observation_json())["source"],
                         "cypher:tools/queries/recent_changes.cypher")
        self.assertEqual(call(ctx, "inspect_recent_changes", {"service": "notify-svc"}).result, [])
        self.assertEqual(len(call(ctx, "inspect_recent_changes",
                                  {"service": "notify-svc", "hours": 8}).result), 1)

    def test_evidence_tools_need_evidence(self):
        bare = ToolContext(graph=None, evidence=None, scenario_now=0)
        with self.assertRaises(ToolError):
            call(bare, "inspect_metrics", {"node": "postgres-orders"})


if __name__ == "__main__":
    unittest.main()
