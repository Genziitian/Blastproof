"""Investigator planning, offline: python -m unittest tests.test_planning -v"""
from __future__ import annotations

import unittest

from agents.contracts import Call, Diagnosis, Step
from agents.planning import RuleBasedPlanner
from eval import truth
from sim.families import Evidence
from tests.reference import upstream_candidates
from tools import registry
from tools.context import ToolContext


def investigate(scenario_id: str) -> tuple[Diagnosis, list[Step], list[Call]]:
    """Run the planner to a conclusion, answering graph tools from the reference."""
    t = truth.load(scenario_id)
    sc = t.scenario()
    ctx = ToolContext(graph=None, evidence=Evidence(sc), scenario_now=sc.now_ms)
    planner, history, calls = RuleBasedPlanner(), [], []
    while True:
        move = planner.next(list(sc.alerting), history)
        if isinstance(move, Diagnosis):
            return move, history, calls
        calls.append(move)
        if move.tool == "find_upstream_candidates":
            observation = upstream_candidates(move.args["alerting"])
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

    def test_db_saturation_takes_six_steps(self):
        _, history, _ = investigate("s01")
        self.assertEqual([s.tool for s in history], [
            "find_upstream_candidates",
            "inspect_recent_changes", "inspect_recent_changes", "inspect_recent_changes",
            "inspect_metrics", "inspect_metrics",
        ])

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
