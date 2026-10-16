"""Investigator planning, offline: python -m unittest tests.test_planning -v"""
from __future__ import annotations

import unittest

from agents.contracts import Call, Diagnosis, Step
from agents.planning import RuleBasedPlanner
from eval import truth
from sim import world as W
from sim.families import Evidence, Scenario
from tests.reference import upstream_candidates
from tools import registry
from tools.context import ToolContext


def investigate(scenario: str | Scenario) -> tuple[Diagnosis, list[Step], list[Call]]:
    """Run the planner to a conclusion, answering graph tools from the reference."""
    sc = truth.load(scenario).scenario() if isinstance(scenario, str) else scenario
    ctx = ToolContext(graph=None, evidence=Evidence(sc), scenario_now=sc.now_ms)
    planner, history, calls = RuleBasedPlanner(), [], []
    while True:
        move = planner.next(list(sc.alerting), history)
        if isinstance(move, Diagnosis):
            return move, history, calls
        calls.append(move)
        if move.tool == "find_upstream_candidates":
            observation = upstream_candidates(move.args["alerting"])
        elif move.tool == "inspect_recent_changes":  # a graph tool; same data as published
            observation = ctx.require_evidence().inspect_recent_changes(**move.args)
        else:
            observation = registry.call(ctx, move.tool, move.args).result
        history.append(Step(len(history) + 1, move.tool, move.args, observation))
        if len(history) > 20:
            raise AssertionError("planner did not converge")


class RuleBasedPlannerTests(unittest.TestCase):
    def test_diagnoses_each_family(self):
        for sid in truth.all_ids():
            t = truth.load(sid)
            diagnosis, history, _ = investigate(sid)
            with self.subTest(scenario=sid):
                self.assertEqual((diagnosis.root, diagnosis.family), (t.root, t.family))
                self.assertTrue(diagnosis.evidence_steps)
                self.assertLessEqual(len(history), 12)

    def test_db_saturation_stops_at_the_first_saturated_datastore(self):
        _, history, _ = investigate("s01")
        self.assertEqual([s.tool for s in history], [
            "find_upstream_candidates",
            "inspect_recent_changes", "inspect_recent_changes", "inspect_recent_changes",
            "inspect_metrics",
        ])
        self.assertEqual(history[-1].args, {"node": "postgres-orders"})

    def test_new_sibling_datastores_are_diagnosed(self):
        """The stores added for the related-service eval category: postgres-menu, redis-sessions."""
        t0 = W.WORLD_START_MS + 9 * 86_400_000
        for family, root in [("db_saturation", "postgres-menu"),
                             ("cache_failure", "redis-sessions")]:
            diagnosis, history, _ = investigate(Scenario("sx", family, root, t0))
            with self.subTest(root=root):
                self.assertEqual((diagnosis.root, diagnosis.family), (root, family))
                self.assertLessEqual(len(history), 6)

    def test_resumes_from_any_checkpoint(self):
        """A worker taking over after step k must ask for exactly step k + 1."""
        for sid in truth.all_ids():
            diagnosis, history, calls = investigate(sid)
            planner = RuleBasedPlanner()
            alerting = list(truth.load(sid).scenario().alerting)
            for k in range(len(history)):
                with self.subTest(scenario=sid, after_step=k):
                    self.assertEqual(planner.next(alerting, history[:k]), calls[k])
            self.assertEqual(planner.next(alerting, history), diagnosis)

    def test_order_of_alerts_does_not_matter(self):
        t = truth.load("s01")
        sc = t.scenario()
        planner = RuleBasedPlanner()
        self.assertEqual(planner.next(list(sc.alerting), []),
                         planner.next(list(reversed(sc.alerting)), []))

    def test_no_evidence_gives_unknown(self):
        diagnosis = RuleBasedPlanner()._conclude([])
        self.assertEqual(diagnosis.root, "unknown")


if __name__ == "__main__":
    unittest.main()
