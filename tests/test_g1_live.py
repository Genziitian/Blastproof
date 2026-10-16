"""Gate G1: one incident end to end, for every scenario, plus a takeover.

    python -m unittest tests.test_g1_live -v

Seeds a scratch graph, runs scenarios end to end, and checks the G1 pass criteria:
every step checkpointed, exactly one notification, the decision confirmed and a
Learn task processed. Also kills an investigator mid-run and checks the takeover.
Runs on the graph double always, and on FalkorDB when it is reachable.
"""
from __future__ import annotations

import contextlib
import unittest
from typing import Any

from agents.investigator import Investigator
from agents.responder import Responder
from agents.triage import incident_key, open_incident
from common.db import run
from eval import truth
from eval.oracle import Oracle
from scripts.run_incident import run_incident
from scripts.seed import seed_graph
from sim import deploys
from sim.runtime import SimulatedWorld
from tests.backends import SKIP_REASON, double, expire_lease, falkordb, falkordb_up
from tests.reference import upstream_candidates

GRAPH = "test_g1"


class Crash(Exception):
    """Stands in for the process dying: not caught by the worker loop."""


class CrashingInvestigator(Investigator):
    def __init__(self, *args, crash_after: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.crash_after = crash_after

    def check_lease(self) -> None:
        super().check_lease()
        done = len(run(self.graph, "coord/queries/read_checkpoints.cypher",
                       {"task_id": self._task_id}))
        if done >= self.crash_after:
            raise Crash

    def handle(self, lease):
        self._task_id = lease.task_id
        super().handle(lease)


class GateG1Cases:
    backend: Any

    def setUp(self):
        self.g = self.backend(GRAPH)
        seed_graph(self.g, "a")

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.g.delete()

    def tasks_of(self, key: str) -> dict[str, dict]:
        rows = run(self.g, "agents/queries/incident_report.cypher", {"incident_key": key})
        return {r["type"]: r for r in rows}

    def outcome(self, key: str) -> dict:
        return run(self.g, "agents/queries/incident_outcome.cypher", {"incident_key": key})[0]

    def test_cypher_matches_reference(self):
        alerting = list(truth.load("s01").scenario().alerting)
        rows = run(self.g, "tools/queries/upstream_candidates.cypher", {"alerting": alerting})
        self.assertEqual(rows, upstream_candidates(alerting))

    def test_each_scenario_end_to_end(self):
        for sid in truth.story_ids():
            t = truth.load(sid)
            with self.subTest(scenario=sid):
                key = run_incident(self.g, t, f"{sid}-live")
                tasks = self.tasks_of(key)
                self.assertEqual(tasks["investigate"]["status"], "done")
                self.assertGreater(tasks["investigate"]["checkpoints"], 0)
                self.assertEqual(tasks["respond"]["status"], "done")
                self.assertEqual(tasks["respond"]["actions"], 1)
                self.assertEqual(tasks["learn"]["status"], "done")
                o = self.outcome(key)
                self.assertEqual((o["root"], o["family"]), (t.root, t.family))
                self.assertEqual(o["verdict"], "confirmed")
                self.assertEqual(o["notified"], [t.expected_recipient])
                self.assertEqual(o["status"], "resolved")

    def test_rerunning_the_responder_does_not_notify_twice(self):
        key = run_incident(self.g, truth.load("s01"), "s01-twice")
        self.assertFalse(Responder(self.g, "late-responder", Oracle()).run_once())
        self.assertEqual(self.tasks_of(key)["respond"]["actions"], 1)

    def test_takeover_resumes_from_last_checkpoint(self):
        t = truth.load("s01")
        world, oracle = SimulatedWorld(), Oracle()
        key = incident_key("s01-crash")
        alerts = world.start(key, t.scenario())
        deploys.publish(self.g, key, t.scenario())
        oracle.watch(key, t)
        open_incident(self.g, "s01-crash", alerts, world.observed_at(key))

        with self.assertRaises(Crash):
            CrashingInvestigator(self.g, "inv-1", world, crash_after=3).run_once()
        expire_lease(self.g, f"{key}:investigate")

        self.assertTrue(Investigator(self.g, "inv-2", world).run_once())
        Responder(self.g, "resp-1", oracle).run_once()

        checkpoints = run(self.g, "coord/queries/read_checkpoints.cypher",
                          {"task_id": f"{key}:investigate"})
        self.assertEqual([c["n"] for c in checkpoints], [1, 2, 3, 4, 5])
        self.assertEqual({c["epoch"] for c in checkpoints[:3]}, {1})
        self.assertEqual({c["epoch"] for c in checkpoints[3:]}, {2})
        self.assertEqual(self.tasks_of(key)["respond"]["actions"], 1)
        self.assertEqual(self.outcome(key)["verdict"], "confirmed")


class GateG1OnDouble(GateG1Cases, unittest.TestCase):
    backend = staticmethod(double)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class GateG1OnFalkorDB(GateG1Cases, unittest.TestCase):
    backend = staticmethod(falkordb)


if __name__ == "__main__":
    unittest.main()
