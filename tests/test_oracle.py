from __future__ import annotations

import unittest

from agents.contracts import Diagnosis
from eval import truth
from eval.oracle import Oracle
from sim import world as W


class OracleTests(unittest.TestCase):
    def setUp(self):
        self.oracle = Oracle()
        self.oracle.watch("incident:x", truth.load("s01"))

    def test_confirms_matching_diagnosis(self):
        verdict = self.oracle.review("incident:x", Diagnosis("postgres-orders", "db_saturation", ""))
        self.assertTrue(verdict.confirmed)

    def test_rejects_wrong_root_or_family(self):
        for root, family in [("redis-cache", "db_saturation"),
                             ("postgres-orders", "cache_failure"),
                             ("unknown", "unknown")]:
            with self.subTest(root=root, family=family):
                self.assertFalse(self.oracle.review("incident:x", Diagnosis(root, family, "")).confirmed)

    def test_truth_files_agree_with_the_world(self):
        """Expected owner and recipient must follow from sim.world, or the oracle lies."""
        ids = truth.all_ids()
        self.assertGreaterEqual(len(ids), 3)
        for sid in ids:
            t = truth.load(sid)
            with self.subTest(scenario=sid):
                owner = next(team for team, (_, nodes) in W.TEAMS.items() if t.root in nodes)
                on_call = next(h for h, (_, team) in W.PEOPLE["a"].items() if team == owner)
                self.assertEqual(t.expected_owner_team, owner)
                self.assertEqual(t.expected_recipient, on_call)
                self.assertTrue(t.scenario().alerting)


if __name__ == "__main__":
    unittest.main()
