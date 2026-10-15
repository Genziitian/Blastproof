"""Memory core, offline: python -m unittest tests.test_memory -v"""
from __future__ import annotations

import unittest

from eval import truth
from memory.playbook import BindingError, Playbook, bind, check_applies
from memory.recall import DAY_MS, rank
from memory.templates import candidate, template
from sim.families import Evidence
from tests.test_planning import investigate


def observer(scenario_id: str):
    """Answer tool calls from the simulator, numbering them like checkpoints."""
    ev = Evidence(truth.load(scenario_id).scenario())
    calls: list[tuple[str, dict]] = []

    def observe(tool: str, args: dict):
        calls.append((tool, args))
        fn = {"inspect_metrics": lambda a: ev.inspect_metrics(a["node"]),
              "inspect_recent_changes": lambda a: ev.inspect_recent_changes(a["service"]),
              "check_dependency_health": lambda a: ev.check_dependency_health(a["service"])}[tool]
        return len(calls), fn(args)

    return observe, calls


class TemplateTests(unittest.TestCase):
    def test_candidates_come_from_what_the_run_observed(self):
        for sid, signature in [("s01", "db_saturation:postgres"), ("s02", "bad_deploy:service"),
                               ("s03", "cache_failure:redis"), ("s04", "db_saturation:postgres")]:
            t = truth.load(sid)
            diagnosis, history, _ = investigate(sid)
            kind = {"postgres-orders": "postgres", "postgres-payments": "postgres",
                    "redis-cache": "redis"}.get(t.root, "service")
            with self.subTest(scenario=sid):
                pb = candidate(diagnosis.family, diagnosis.root, kind, history)
                self.assertIsNotNone(pb)
                self.assertEqual(pb.signature, signature)

    def test_no_candidate_without_confirming_evidence(self):
        self.assertIsNone(candidate("db_saturation", "postgres-orders", "postgres", []))
        self.assertIsNone(candidate("unknown", "x", "service", []))

    def test_storage_round_trip(self):
        pb = template("db_saturation", "postgres")
        fields = pb.fields()
        self.assertEqual(len(fields["payload_hash"]), 16)
        self.assertEqual(Playbook.from_record(fields), pb)
        self.assertEqual(template("db_saturation", "postgres").fields()["payload_hash"],
                         fields["payload_hash"], "hash must be stable across runs")


class ApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.db = template("db_saturation", "postgres")

    def test_applies_where_it_was_learned(self):
        observe, calls = observer("s01")
        result = check_applies(self.db, bind(["cart-svc", "postgres-orders"], "postgres-orders"),
                               observe)
        self.assertTrue(result.applies)
        self.assertEqual(result.root, "postgres-orders")
        self.assertEqual(len(calls), 3, "two preconditions and one confirming step")

    def test_transfers_to_a_sibling_datastore(self):
        observe, _ = observer("s04")
        result = check_applies(self.db, bind(["payments-gw", "postgres-payments"],
                                             "postgres-payments"), observe)
        self.assertTrue(result.applies)
        self.assertEqual(result.root, "postgres-payments")

    def test_rejected_on_evidence_when_symptoms_match_but_cause_differs(self):
        observe, _ = observer("s05")  # bad deploy on checkout-api, same checkout timeouts
        result = check_applies(self.db, bind(["checkout-api", "cart-svc", "postgres-orders"],
                                             "postgres-orders"), observe)
        self.assertFalse(result.applies)
        self.assertEqual(result.failed.phase, "precondition")
        self.assertIn("deploys", result.failed.description)
        self.assertEqual(result.failed.observed, 1)

    def test_wrong_target_fails_fast(self):
        observe, calls = observer("s04")  # postgres-payments is the real cause
        result = check_applies(self.db, bind(["checkout-api", "cart-svc", "postgres-orders"],
                                             "postgres-orders"), observe)
        self.assertFalse(result.applies)
        self.assertLessEqual(len(calls), 2)

    def test_unbound_parameter_is_an_error(self):
        observe, _ = observer("s01")
        with self.assertRaises(BindingError):
            check_applies(self.db, bind(["postgres-orders"], "postgres-orders"), observe)


class RecallRankingTests(unittest.TestCase):
    NOW = 100 * DAY_MS

    def row(self, mid, alerting, target, hops, weight=1.0, trust=0.5, age_days=0, path=None):
        return {"id": mid, "alerting": alerting, "target": target, "hops": hops,
                "weight": weight, "trust": trust, "recorded_at": self.NOW - age_days * DAY_MS,
                "path": path or [alerting, target]}

    def test_each_alerting_service_adds_its_own_contribution(self):
        one = rank([self.row("m1", "a", "db", 1)], self.NOW)[0]
        two = rank([self.row("m1", "a", "db", 1), self.row("m1", "b", "db", 1)], self.NOW)[0]
        self.assertAlmostEqual(two.score, 2 * one.score)

    def test_closer_trusted_fresh_memories_rank_first(self):
        # near 0.5 > doubted 0.2 > far (2 hops) 0.125 > old (60 days) 0.068
        ranked = rank([
            self.row("far", "a", "db", 2),
            self.row("near", "a", "db", 0),
            self.row("old", "a", "db", 0, age_days=60),
            self.row("doubted", "a", "db", 0, trust=0.2),
        ], self.NOW)
        self.assertEqual([r.memory_id for r in ranked], ["near", "doubted", "far", "old"])

    def test_one_memory_many_targets_are_separate_candidates(self):
        ranked = rank([
            self.row("pb", "checkout-api", "postgres-orders", 2),
            self.row("pb", "payments-gw", "postgres-payments", 1, weight=0.5),
        ], self.NOW)
        self.assertEqual({r.target for r in ranked}, {"postgres-orders", "postgres-payments"})
        self.assertTrue(next(r for r in ranked if r.target == "postgres-payments").via_kind)

    def test_binding_path_prefers_strongest_then_alphabetical(self):
        ranked = rank([
            self.row("pb", "web-gateway", "db", 2, path=["web-gateway", "cart-svc", "db"]),
            self.row("pb", "checkout-api", "db", 2, path=["checkout-api", "cart-svc", "db"]),
        ], self.NOW)
        self.assertEqual(ranked[0].path[0], "checkout-api")

    def test_keeps_top_k(self):
        rows = [self.row(f"m{i}", "a", "db", 0) for i in range(9)]
        self.assertEqual(len(rank(rows, self.NOW, k=5)), 5)


if __name__ == "__main__":
    unittest.main()
