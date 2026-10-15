"""Trust arithmetic behind the plan's claims (A2)."""
from __future__ import annotations

import unittest

from memory.feedback import retired, trust, verdicts


class VerdictTests(unittest.TestCase):
    def test_only_followed_memories_are_credited_or_blamed(self):
        usage = [{"id": "pb1", "target": "db1", "applied": True, "verdict": None},
                 {"id": "pb1", "target": "db2", "applied": False, "verdict": None},
                 {"id": "pb2", "target": "db1", "applied": False, "verdict": None}]
        self.assertEqual([v["verdict"] for v in verdicts(usage, confirmed=True)],
                         ["helped", "not_applicable", "not_applicable"])
        self.assertEqual([v["verdict"] for v in verdicts(usage, confirmed=False)],
                         ["misled", "not_applicable", "not_applicable"])

    def test_already_judged_edges_are_skipped(self):
        usage = [{"id": "pb1", "target": "db1", "applied": True, "verdict": "helped"}]
        self.assertEqual(verdicts(usage, confirmed=False), [])


class TrustTests(unittest.TestCase):
    def test_priors(self):
        self.assertEqual(trust(0, 0, "agent"), 0.5)
        self.assertAlmostEqual(trust(0, 0, "human"), 2 / 3)

    def test_zero_success_playbook_retires_on_second_misleading_use(self):
        for source in ("agent", "human"):
            with self.subTest(source=source):
                self.assertFalse(retired(0, 1, source))
                self.assertTrue(retired(0, 2, source))

    def test_established_playbook_follows_the_threshold(self):
        """The plan's narrowed claim: two misleads alone don't retire a proven playbook."""
        self.assertEqual(trust(2, 2, "agent"), 0.5)
        self.assertFalse(retired(2, 2, "agent"))
        self.assertTrue(retired(2, 3, "agent"))


if __name__ == "__main__":
    unittest.main()
