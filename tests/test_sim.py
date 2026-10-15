"""Simulator tests. No database needed:  python -m unittest tests.test_sim -v"""
from __future__ import annotations

import json
import unittest

from sim import world as W
from sim.families import Evidence, Scenario, callers_of

T0 = W.WORLD_START_MS + 5 * 24 * 3_600_000


def dump(ev: Evidence, nodes) -> str:
    out = {}
    for n in nodes:
        out[n] = {"m": ev.inspect_metrics(n), "l": ev.inspect_logs(n)}
        if n in W.SERVICES:
            out[n]["c"] = ev.inspect_recent_changes(n)
            out[n]["h"] = ev.check_dependency_health(n)
    return json.dumps(out, sort_keys=True)


class SimTests(unittest.TestCase):
    def test_world_is_consistent(self):
        nodes = set(W.SERVICES) | set(W.DATASTORES)
        for a, b in W.DEPENDS_ON:
            self.assertIn(a, nodes)
            self.assertIn(b, nodes)
        owned = [n for _, (_, ns) in W.TEAMS.items() for n in ns]
        self.assertEqual(sorted(owned), sorted(nodes), "every node has exactly one owner team")
        self.assertEqual(set(W.PEOPLE["a"]), set(W.PEOPLE["b"]), "same handles in both tenants")
        self.assertNotEqual(W.CANARY["a"], W.CANARY["b"])

    def test_deterministic(self):
        s = Scenario("s01", "db_saturation", "postgres-orders", T0)
        nodes = list(W.SERVICES) + list(W.DATASTORES)
        self.assertEqual(dump(Evidence(s), nodes), dump(Evidence(s), nodes))

    def test_same_symptom_different_evidence(self):
        db = Scenario("s10", "db_saturation", "postgres-orders", T0)
        dep = Scenario("s11", "bad_deploy", "checkout-api", T0)
        self.assertIn("checkout-api", db.alerting)
        self.assertIn("checkout-api", dep.alerting)
        e_db, e_dep = Evidence(db), Evidence(dep)
        # Both look like checkout latency trouble...
        self.assertGreater(e_db.inspect_metrics("checkout-api")["latency_p95_ms"][-1], 1000)
        self.assertGreater(e_dep.inspect_metrics("checkout-api")["latency_p95_ms"][-1], 1000)
        # ...but recent changes and the database tell them apart.
        self.assertEqual(e_db.inspect_recent_changes("checkout-api"), [])
        self.assertEqual(len(e_dep.inspect_recent_changes("checkout-api")), 1)
        self.assertGreaterEqual(e_db.inspect_metrics("postgres-orders")["db_connections_pct"][-1], 90)
        self.assertLess(e_dep.inspect_metrics("postgres-orders")["db_connections_pct"][-1], 60)

    def test_cache_failure_shows_db_load_but_not_saturation(self):
        s = Scenario("s20", "cache_failure", "redis-cache", T0)
        ev = Evidence(s)
        self.assertLess(ev.inspect_metrics("redis-cache")["cache_hit_rate_pct"][-1], 20)

    def test_wording_variants_differ(self):
        a = Evidence(Scenario("s30", "db_saturation", "postgres-orders", T0, wording=0))
        b = Evidence(Scenario("s30", "db_saturation", "postgres-orders", T0, wording=1))
        self.assertNotEqual(a.alerts()[0]["text"], b.alerts()[0]["text"])

    def test_answer_never_leaks_into_evidence(self):
        for fam, root in [("db_saturation", "postgres-orders"), ("bad_deploy", "checkout-api"),
                          ("cache_failure", "redis-cache")]:
            s = Scenario("s40", fam, root, T0)
            blob = dump(Evidence(s), list(W.SERVICES) + list(W.DATASTORES)).lower()
            blob += json.dumps(Evidence(s).alerts()).lower()
            for word in ("db_saturation", "bad_deploy", "cache_failure", "root_cause", "family"):
                self.assertNotIn(word, blob, f"{word!r} leaked for {fam}")

    def test_callers(self):
        self.assertEqual(callers_of("postgres-orders"),
                         {"cart-svc", "orders-svc", "checkout-api", "web-gateway"})


if __name__ == "__main__":
    unittest.main()
