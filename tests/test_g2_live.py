"""Gate G2: memory that transfers, gets ruled out, loses trust, and survives crashes.

    python -m unittest tests.test_g2_live -v

The demo story on a scratch graph:
  s01  DB saturation on postgres-orders; Priya asks for tickets with raw lines
  s04  related outage on postgres-payments, new wording; the playbook transfers
  s05  same checkout symptoms, but a bad deploy; the DB playbook is ruled out

Plus the seven acceptance checks (with an in-process crash in place of SIGKILL),
a playbook that misleads twice and is retired, and crashes around learning.
Runs on the graph double always, and on FalkorDB when it is reachable.
"""
from __future__ import annotations

import contextlib
import json
import unittest
from typing import Any

from agents.contracts import Diagnosis, Verdict
from agents.investigator import Investigator
from agents.learner import Learner
from agents.responder import Responder
from agents.triage import incident_key, open_incident
from chat.war_room import WarRoom
from common.db import run
from eval import truth
from eval.oracle import Oracle
from scripts import acceptance
from scripts.run_incident import run_incident
from scripts.seed import seed_graph
from sim.runtime import SimulatedWorld
from tests.backends import SKIP_REASON, double, expire_lease, falkordb, falkordb_up
from tests.graph_double import GraphDouble
from tests.test_g1_live import Crash, CrashingInvestigator

DB_PLAYBOOK = "db_saturation:postgres"


def q(g: Any, cypher: str, **params: Any) -> list[list[Any]]:
    return g.query(cypher, params).result_set


def memory_of(g: Any, key: str) -> list[dict[str, Any]]:
    return run(g, "agents/queries/incident_memory.cypher", {"incident_key": key})


def outcome(g: Any, key: str) -> dict[str, Any]:
    return run(g, "agents/queries/incident_outcome.cypher", {"incident_key": key})[0]


def checkpoints(g: Any, key: str) -> list[dict[str, Any]]:
    return run(g, "coord/queries/read_checkpoints.cypher", {"task_id": f"{key}:investigate"})


def actions(g: Any, key: str) -> list[list[Any]]:
    return q(g, "MATCH (:Incident {key: $k})<-[:FOR]-(:Task)-[:EMITTED]->(a:Action) "
                "RETURN a.recipient, a.channel, a.payload", k=key)


def playbook(g: Any, signature: str) -> list[list[Any]]:
    return q(g, "MATCH (p:Memory:Playbook {signature: $s}) "
                "RETURN p.helped, p.misled, p.trust, p.status", s=signature)


class Rejects:
    """An engineer who rejects every diagnosis."""

    def review(self, incident_key: str, diagnosis: Diagnosis) -> Verdict:
        return Verdict(confirmed=False, by="test")


class StoryCases:
    backend: Any

    @classmethod
    def setUpClass(cls):
        cls.g = cls.backend("test_g2")
        seed_graph(cls.g, "a")
        cls.keys = {sid: run_incident(cls.g, truth.load(sid), f"{sid}-story")
                    for sid in ("s01", "s04", "s05")}
        # The same s04 incident investigated without memory: the honest M1 baseline.
        cls.baseline = run_incident(cls.g, truth.load("s04"), "s04-nomem",
                                    use_memory=False, learn=False)

    @classmethod
    def tearDownClass(cls):
        with contextlib.suppress(Exception):
            cls.g.delete()

    def test_every_diagnosis_is_right(self):
        for sid, key in self.keys.items():
            t, o = truth.load(sid), outcome(self.g, key)
            with self.subTest(scenario=sid):
                self.assertEqual((o["root"], o["family"], o["verdict"]),
                                 (t.root, t.family, "confirmed"))

    def test_s01_leaves_a_sourced_playbook_and_preferences(self):
        pb = q(self.g, "MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) "
                       "MATCH (p)-[:ABOUT]->(n) RETURN p.signature, n.name", k=self.keys["s01"])
        self.assertIn([DB_PLAYBOOK, "postgres-orders"], pb)
        prefs = q(self.g, "MATCH (f:Memory:Fact)-[:ABOUT]->(:Person {key: 'person:priya'}) "
                          "RETURN f.predicate, f.object, f.condition_family, f.source")
        self.assertIn(["preferred_channel", "ticket", "db_saturation", "human"], prefs)
        self.assertIn(["wants_detail", "raw_logs", "db_saturation", "human"], prefs)

    def test_s04_recalls_by_kind_and_needs_fewer_steps(self):
        applied = [(u["memory"], u["target"], u["verdict"])
                   for u in memory_of(self.g, self.keys["s04"]) if u["applied"]]
        self.assertEqual(applied, [("pb-dec-s01-story", "postgres-payments", "helped")])
        self.assertLess(len(checkpoints(self.g, self.keys["s04"])),
                        len(checkpoints(self.g, self.baseline)))

    def test_s04_applies_and_cites_the_preference_once(self):
        [(recipient, channel, payload)] = actions(self.g, self.keys["s04"])
        self.assertEqual((recipient, channel), ("priya", "ticket"))
        body = json.loads(payload)
        self.assertEqual(len(body["applied_preferences"]), 1, "one message, one citation")
        self.assertIn("s01-story", body["applied_preferences"][0])
        self.assertIn("Raw lines:", body["text"])
        self.assertEqual(body["text"].count("Sent this way"), 1)

    def test_s05_rules_the_db_playbook_out_on_evidence(self):
        uses = memory_of(self.g, self.keys["s05"])
        self.assertTrue(uses)
        self.assertTrue(all(not u["applied"] and u["verdict"] == "not_applicable" for u in uses))
        helped, misled, _, status = playbook(self.g, DB_PLAYBOOK)[0]
        self.assertEqual((helped, misled, status), (1, 0, "active"),
                         "ruled out is not misled: trust only rose from s04")

    def test_s05_preferences_do_not_leak_across_people_or_conditions(self):
        [(recipient, channel, _)] = actions(self.g, self.keys["s05"])
        self.assertEqual((recipient, channel), ("rohan", "page"))

    def test_s05_teaches_a_new_playbook(self):
        sigs = q(self.g, "MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) "
                         "RETURN p.id, p.signature", k=self.keys["s05"])
        self.assertEqual([s for _, s in sigs], ["bad_deploy:service"])

    def test_a_new_session_can_resume_the_conversation(self):
        recent = WarRoom(self.g).recent("priya", limit=3)
        self.assertEqual([m["role"] for m in recent], ["agent", "engineer", "agent"])
        self.assertEqual({m["incident"] for m in recent}, {"s01-story"})

    def test_every_parameter_is_read(self):
        if not isinstance(self.g, GraphDouble):
            self.skipTest("the double records parameters a query never reads")
        self.assertEqual(self.g.unused_params, [])

    def test_conversation_is_stored_verbatim(self):
        said = q(self.g, "MATCH (m:Message {role: 'engineer'})-[:IN]->(:Session)-[:CONCERNS]->"
                         "(:Incident {key: $k}) RETURN m.text", k=self.keys["s01"])
        self.assertEqual(said, [[truth.load("s01").engineer_says]])


class AcceptanceCases:
    """scripts/acceptance.py's seven checks, with an in-process crash for the kill.

    The real run (make acceptance-1, restart, make acceptance-2) adds what only the
    stack can show: a SIGKILLed process and a database restart between the parts.
    """
    backend: Any

    def setUp(self):
        self.g = self.backend("test_acceptance")
        seed_graph(self.g, "a")

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.g.delete()

    def test_seven_checks_pass(self):
        run_incident(self.g, truth.load("s01"), "s01-acc")

        t, world, oracle = truth.load("s04"), SimulatedWorld(), Oracle()
        key = incident_key("s04-acc")
        open_incident(self.g, "s04-acc", world.start(key, t.scenario()), world.observed_at(key))
        oracle.watch(key, t)
        with self.assertRaises(Crash):
            CrashingInvestigator(self.g, "worker-1", world,
                                 crash_after=acceptance.KILL_AFTER).run_once()
        expire_lease(self.g, f"{key}:investigate")
        self.assertTrue(Investigator(self.g, "worker-2", world).run_once())
        Responder(self.g, "responder-1", oracle, world).run_once()
        Learner(self.g, "learner-1").run_once()

        self.assertEqual(acceptance.report(self.g, "s01-acc", "s04-acc"), 0)


class MemoryLifecycleCases:
    backend: Any

    def setUp(self):
        self.g = self.backend("test_memory")
        seed_graph(self.g, "a")
        self.s01 = run_incident(self.g, truth.load("s01"), "s01-m")

    def tearDown(self):
        with contextlib.suppress(Exception):
            self.g.delete()

    def test_a_playbook_that_misleads_twice_is_retired_and_relearned(self):
        s04 = truth.load("s04")
        first = run_incident(self.g, s04, "s04-m1", confirmer=Rejects())
        self.assertEqual(outcome(self.g, first)["status"], "needs_review")
        self.assertEqual(playbook(self.g, DB_PLAYBOOK)[0][:2], [0, 1])

        run_incident(self.g, s04, "s04-m2", confirmer=Rejects())
        helped, misled, trust, status = playbook(self.g, DB_PLAYBOOK)[0]
        self.assertEqual((helped, misled, status), (0, 2, "retired"))
        self.assertLess(trust, 0.5)

        third = run_incident(self.g, s04, "s04-m3")
        self.assertEqual(memory_of(self.g, third), [], "a retired playbook is not recalled")
        self.assertEqual(outcome(self.g, third)["verdict"], "confirmed")
        statuses = sorted(row[3] for row in playbook(self.g, DB_PLAYBOOK))
        self.assertEqual(statuses, ["active", "retired"], "relearned from fresh evidence")

    def test_a_second_confirmed_run_adds_a_source_not_a_duplicate(self):
        key = run_incident(self.g, truth.load("s04"), "s04-p", use_memory=False)
        self.assertEqual(len(playbook(self.g, DB_PLAYBOOK)), 1)
        sources = q(self.g, "MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) "
                            "RETURN p.id", k=key)
        self.assertEqual(sources, [["pb-dec-s01-m"]])

    def test_crash_between_confirmation_and_learning_loses_nothing(self):
        key = run_incident(self.g, truth.load("s04"), "s04-c", learn=False)
        self.assertEqual(playbook(self.g, DB_PLAYBOOK)[0][:2], [0, 0], "not learned yet")
        self.assertTrue(Learner(self.g, "learner-late").run_once())
        self.assertEqual(playbook(self.g, DB_PLAYBOOK)[0][:2], [1, 0])
        self.assertEqual(outcome(self.g, key)["status"], "resolved")

    def test_a_retried_learner_does_not_count_a_verdict_twice(self):
        run_incident(self.g, truth.load("s04"), "s04-r", learn=False)

        class DiesBeforeCompleting(Learner):
            def check_lease(self) -> None:
                raise Crash

        with self.assertRaises(Crash):
            DiesBeforeCompleting(self.g, "learner-1").run_once()
        self.assertEqual(playbook(self.g, DB_PLAYBOOK)[0][:2], [1, 0])
        expire_lease(self.g, "learn:dec-s04-r")
        self.assertTrue(Learner(self.g, "learner-2").run_once())
        self.assertEqual(playbook(self.g, DB_PLAYBOOK)[0][:2], [1, 0])


class StoryOnDouble(StoryCases, unittest.TestCase):
    backend = staticmethod(double)


class AcceptanceOnDouble(AcceptanceCases, unittest.TestCase):
    backend = staticmethod(double)


class MemoryLifecycleOnDouble(MemoryLifecycleCases, unittest.TestCase):
    backend = staticmethod(double)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class StoryOnFalkorDB(StoryCases, unittest.TestCase):
    backend = staticmethod(falkordb)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class AcceptanceOnFalkorDB(AcceptanceCases, unittest.TestCase):
    backend = staticmethod(falkordb)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class MemoryLifecycleOnFalkorDB(MemoryLifecycleCases, unittest.TestCase):
    backend = staticmethod(falkordb)


if __name__ == "__main__":
    unittest.main()
