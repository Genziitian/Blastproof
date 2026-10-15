"""Coordination: claim, fence, checkpoint, action, handoff, attempts, stuck sweep.

    python -m unittest tests.test_coord_live -v

Runs on the graph double always, and on FalkorDB when it is reachable
(docker compose up -d falkordb). Uses a scratch graph and deletes it afterwards.
"""
from __future__ import annotations

import contextlib
import threading
import unittest
from typing import Any

from common import config
from coord import tasks as T
from coord.tasks import Outcome
from tests.backends import SKIP_REASON, count, double, expire_lease, falkordb, falkordb_up

GRAPH = "test_coord"


class CoordCases:
    backend: Any

    def setUp(self):
        self.g = self.backend(GRAPH)
        self.g.query("CREATE (:Incident {key: 'incident:t1', status: 'open'})")

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.g.delete()

    def test_full_lifecycle_with_takeover(self):
        T.create_task(self.g, "t1:investigate", "investigate", "incident:t1")
        T.create_task(self.g, "t1:investigate", "investigate", "incident:t1")  # idempotent
        self.assertEqual(count(self.g, "Task"), 1)

        r1, w1 = T.claim(self.g, "investigate", "w1")
        self.assertEqual(r1.outcome, Outcome.OK)
        self.assertEqual(w1.epoch, 1, "epoch must start at 0 so the first claim gives 1")
        self.assertEqual(T.claim(self.g, "investigate", "w2")[0].outcome, Outcome.NONE)

        self.assertEqual(T.heartbeat(self.g, w1).outcome, Outcome.OK)
        first = T.checkpoint(self.g, w1, 1, "inspect_metrics", {"node": "x"}, "ok", 0)
        self.assertEqual(first.outcome, Outcome.OK)
        T.checkpoint(self.g, w1, 1, "inspect_metrics", {"node": "x"}, "ok", 0)  # retry
        self.assertEqual(count(self.g, "Checkpoint"), 1)

        a = T.send_action(self.g, w1, "t1:initial-notification", "ticket", "priya", "ticket",
                          {"x": 1})
        self.assertEqual(a.outcome, Outcome.OK)
        again = T.send_action(self.g, w1, "t1:initial-notification", "ticket", "priya",
                              "ticket", {"x": 1})
        self.assertEqual(again.outcome, Outcome.ALREADY_DONE)

        # w1 stalls past its lease; w2 takes over.
        expire_lease(self.g, w1.task_id)
        self.assertEqual(T.heartbeat(self.g, w1).outcome, Outcome.LEASE_LOST)
        # A retry of a send that already happened is reported as done, not lost.
        late = T.send_action(self.g, w1, "t1:initial-notification", "ticket", "priya", "ticket",
                             {"x": 1})
        self.assertEqual(late.outcome, Outcome.ALREADY_DONE)
        r2, w2 = T.claim(self.g, "investigate", "w2")
        self.assertEqual((r2.outcome, w2.epoch), (Outcome.OK, 2))

        # The stale worker can't write any more.
        stale = T.checkpoint(self.g, w1, 2, "x", {}, "stale", 0)
        self.assertEqual(stale.outcome, Outcome.LEASE_LOST)
        self.assertEqual(T.handoff(self.g, w1, "respond").outcome, Outcome.LEASE_LOST)

        # w2 resumes from the checkpoint and can't double-notify, even with a new recipient.
        self.assertEqual([c["n"] for c in T.read_checkpoints(self.g, w2.task_id)], [1])
        dup = T.send_action(self.g, w2, "t1:initial-notification", "ticket", "kabir", "slack",
                            {"x": 2})
        self.assertEqual(dup.outcome, Outcome.ALREADY_DONE)
        self.assertEqual(dup.data["recipient"], "priya")
        self.assertEqual(count(self.g, "Action"), 1)

        h = T.handoff(self.g, w2, "respond")
        self.assertEqual(h.outcome, Outcome.OK)
        h2 = T.handoff(self.g, w2, "respond")
        self.assertEqual((h2.outcome, h2.data["next_id"]),
                         (Outcome.ALREADY_DONE, h.data["next_id"]))
        self.assertEqual(count(self.g, "Task", type="respond"), 1)

    def test_race_only_one_winner(self):
        T.create_task(self.g, "t1:race", "race", "incident:t1")
        results, lock = [], threading.Lock()

        def go(i):
            r, _ = T.claim(self.g, "race", f"w{i}")
            with lock:
                results.append(r.outcome)

        threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(Outcome.OK), 1, results)

    def test_attempts_limit_and_stuck_sweep(self):
        T.create_task(self.g, "t1:poison", "poison", "incident:t1")
        for i in range(config.MAX_ATTEMPTS):
            r, lease = T.claim(self.g, "poison", f"w{i}")
            self.assertEqual(r.outcome, Outcome.OK)
            expire_lease(self.g, lease.task_id)
        self.assertEqual(T.claim(self.g, "poison", "w9")[0].outcome, Outcome.NONE)
        self.assertEqual(T.stuck_sweep(self.g), ["t1:poison"])


class CoordOnDouble(CoordCases, unittest.TestCase):
    backend = staticmethod(double)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class CoordOnFalkorDB(CoordCases, unittest.TestCase):
    backend = staticmethod(falkordb)


if __name__ == "__main__":
    unittest.main()
