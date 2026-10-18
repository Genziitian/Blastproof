"""The load benchmark and the isolation check, small, on both backends."""
from __future__ import annotations

import unittest
from typing import Any

from bench.fencing import check as check_fencing
from bench.isolation import check
from bench.load import run_load
from tests.backends import SKIP_REASON, double, falkordb, falkordb_up


class BenchCases:
    backend: Any

    def test_old_lease_cannot_mutate_after_takeover(self):
        result = check_fencing(self.backend)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["stale_writes_rejected"], 5)
        self.assertEqual(result["new_epoch"], result["old_epoch"] + 1)

    def test_concurrent_workers_finish_everything_and_notify_once(self):
        r = run_load(lambda n: self.backend(f"t_{n}"), pairs=2, incidents=8, timeout_s=60)
        self.assertEqual(r["completed"], r["incidents"], r["errors"])
        self.assertEqual(r["duplicate_notifications"], 0)
        self.assertEqual(r["errors"], [])
        self.assertGreater(r["memory_writes"]["n"], 0)

    def test_stalled_workers_are_fenced_out_and_nothing_is_sent_twice(self):
        r = run_load(lambda n: self.backend(f"tc_{n}"), pairs=2, incidents=8, timeout_s=10,
                     chaos_ms=5)
        self.assertEqual(r["duplicate_notifications"], 0)
        self.assertEqual(r["errors"], [])
        # Nothing is lost silently: every incident finished, or a task is flagged for a human.
        self.assertGreaterEqual(r["completed"] + r["stuck_for_a_human"], r["incidents"])

    def test_tenants_stay_isolated(self):
        result = check(lambda n: self.backend(f"t_{n}"))
        self.assertTrue(result["ok"], result)


class BenchOnDouble(BenchCases, unittest.TestCase):
    backend = staticmethod(double)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class BenchOnFalkorDB(BenchCases, unittest.TestCase):
    backend = staticmethod(falkordb)


if __name__ == "__main__":
    unittest.main()
