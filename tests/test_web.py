"""The UI's backend: shared simulator, engineer bridge, read models and HTTP API.

    python -m unittest tests.test_web -v

The demo story is driven through `web.demo.Demo` exactly as the UI drives it (the
UI breaks things and plays the engineer; agents do the rest), and every panel's
read model is checked: Memory Lens, live recall, agent timeline with a takeover,
war room, pager log, memory catalogue, org chart. Runs on the graph double always,
and on FalkorDB when it is reachable.
"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from typing import Any

from fastapi.testclient import TestClient

from agents.contracts import Diagnosis
from agents.investigator import Investigator
from scripts.seed import seed_graph
from sim.families import Scenario
from sim.store import ScenarioStore
from tests.backends import SKIP_REASON, double, expire_lease, falkordb, falkordb_up
from tests.graph_double import GraphDouble
from web.app import create_app, latest_results
from web.demo import Demo
from web.engineer import Cancelled, Engineer, Script


class StoreTests(unittest.TestCase):
    def test_another_process_sees_the_same_evidence(self):
        root = tempfile.mkdtemp()
        sc = Scenario("x1", "db_saturation", "postgres-orders", 1_790_900_000_000, wording=3)
        alerts = ScenarioStore(root).start("incident:x1", sc)
        other = ScenarioStore(root)  # a fresh instance, as in a worker process
        self.assertEqual(other.evidence_for("incident:x1").alerts(), alerts)
        self.assertEqual(other.observed_at("incident:x1"), sc.now_ms)
        self.assertEqual(other.evidence_for("incident:x1").inspect_metrics("postgres-orders"),
                         ScenarioStore(root).evidence_for("incident:x1")
                         .inspect_metrics("postgres-orders"))

    def test_unknown_incident_and_clear(self):
        store = ScenarioStore(tempfile.mkdtemp())
        with self.assertRaises(LookupError):
            store.evidence_for("incident:nope")
        store.start("incident:a", Scenario("a", "cache_failure", "redis-cache", 1))
        store.clear()
        with self.assertRaises(LookupError):
            ScenarioStore(store.root).evidence_for("incident:a")


DIAG = Diagnosis("postgres-orders", "db_saturation", "98% of connections")


class EngineerTests(unittest.TestCase):
    def test_scripted_engineer_confirms_only_the_right_answer(self):
        e = Engineer(autopilot=True)
        e.watch("k", Script("postgres-orders", "db_saturation", "tickets please"))
        v = e.review("k", DIAG)
        self.assertTrue(v.confirmed)
        self.assertEqual(v.message, "tickets please")
        self.assertFalse(e.review("k", Diagnosis("redis-cache", "cache_failure", "")).confirmed)
        self.assertEqual(e.answer("k", "Right?"), "Yes, that's right.")

    def test_person_answers_through_the_ui(self):
        e = Engineer(autopilot=False, handle_for=lambda key: "priya")
        e.watch("k", Script("postgres-orders", "db_saturation", "scripted"))
        out: dict[str, Any] = {}
        t = threading.Thread(target=lambda: out.update(v=e.review("k", DIAG)))
        t.start()
        for _ in range(100):
            if e.pending():
                break
            time.sleep(0.01)
        [p] = e.pending()
        self.assertEqual((p["kind"], p["suggestion"]), ("review", "scripted"))
        self.assertTrue(e.submit("k", {"confirmed": False, "message": "  it's the cache  "}))
        t.join(2)
        self.assertEqual((out["v"].confirmed, out["v"].by, out["v"].message),
                         (False, "priya", "it's the cache"))
        self.assertEqual(e.pending(), [])

    def test_nobody_answers_then_the_script_does(self):
        e = Engineer(autopilot=False, timeout_s=0.3)
        e.watch("k", Script("postgres-orders", "db_saturation"))
        self.assertTrue(e.review("k", DIAG).confirmed)

    def test_reset_while_waiting(self):
        e = Engineer(autopilot=False)
        errors: list[BaseException] = []

        def wait() -> None:
            try:
                e.answer("k", "Right?")
            except Cancelled as err:
                errors.append(err)
        t = threading.Thread(target=wait)
        t.start()
        while not e.pending():
            time.sleep(0.01)
        e.cancel_all()
        t.join(2)
        self.assertEqual(len(errors), 1)


class WebCases:
    backend: Any

    def setUp(self) -> None:
        self.g = self.backend(f"web_{type(self).__name__.lower()}")
        seed_graph(self.g, "a")
        self.store = ScenarioStore(tempfile.mkdtemp())
        self.engineer = Engineer(autopilot=True)
        self.demo = Demo(self.g, "a", self.store, self.engineer)
        self.responder, self.learner = self.demo.agents()

    def investigator(self, name: str) -> Investigator:
        return Investigator(self.g, name, ScenarioStore(self.store.root))  # its own process

    def finish(self, key: str, inv: Investigator | None = None) -> dict[str, Any]:
        if inv is not None:
            self.assertTrue(inv.run_once())
        self.assertTrue(self.responder.run_once())
        self.assertTrue(self.learner.run_once())
        found = self.demo.incident(key)
        assert found is not None
        return found

    def test_story_through_every_panel(self):
        k1 = self.demo.run_story("s01")
        x1 = self.finish(k1, self.investigator("inv-1"))
        self.assertEqual((x1["head"]["root"], x1["head"]["verdict"]),
                         ("postgres-orders", "confirmed"))
        self.assertEqual(x1["lens"], [])
        self.assertEqual([m["role"] for m in x1["messages"]],
                         ["agent", "engineer", "agent", "engineer"])
        kinds = [e["kind"] for e in x1["timeline"]]
        self.assertIn("claim", kinds)
        self.assertIn("checkpoint", kinds)
        self.assertEqual(kinds.count("action"), 1)

        # s04: recalled by kind; the first worker stalls after 3 steps, a second resumes.
        k2 = self.demo.run_story("s04")
        self.assertGreater(self.store.observed_at(k2), self.store.observed_at(k1))
        task = f"{k2}:investigate"
        stalled = self.investigator("inv-1")
        stalled.pace_s = 0.0
        steps = {"n": 0}
        original = stalled._step

        def stop_after_three(*a: Any, **kw: Any) -> Any:
            if steps["n"] == 3:
                raise RuntimeError("SIGKILL")
            steps["n"] += 1
            return original(*a, **kw)
        stalled._step = stop_after_three  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            stalled.run_once()
        live = self.demo.incident(k2)
        assert live is not None
        self.assertTrue(live["recalling"], "recalled memories are shown before the decision")
        self.assertEqual(live["lens"], [])
        [held] = [t for t in live["tasks"] if t["type"] == "investigate"]
        self.assertEqual((held["status"], held["owner"], held["epoch"]), ("leased", "inv-1", 1))
        self.assertGreater(held["lease_left_ms"], 0)
        expire_lease(self.g, task)
        x2 = self.finish(k2, self.investigator("inv-2"))
        takeover = [e for e in x2["timeline"] if e["kind"] == "takeover"]
        self.assertEqual([(e["agent"], e["epoch"]) for e in takeover], [("inv-2", 2)])
        epochs = [(c["n"], c["agent"], c["epoch"]) for c in x2["checkpoints"]]
        self.assertEqual(epochs[:3], [(1, "inv-1", 1), (2, "inv-1", 1), (3, "inv-1", 1)])
        self.assertTrue(all(a == "inv-2" and e == 2 for _, a, e in epochs[3:]))
        applied = [r for r in x2["lens"] if r["applied"]]
        self.assertEqual([(r["target"], r["verdict"]) for r in applied],
                         [("postgres-payments", "helped")])
        self.assertTrue(applied[0]["checks"] and all(c["passed"] for c in applied[0]["checks"]))
        self.assertGreater(applied[0]["trust_after"], applied[0]["trust_at_use"])
        self.assertEqual([(a["recipient"], a["channel"]) for a in x2["actions"]],
                         [("priya", "ticket")])

        # s05: same symptoms, a deploy; the DB playbook is ruled out on evidence.
        x3 = self.finish(self.demo.run_story("s05"), self.investigator("inv-1"))
        self.assertEqual(x3["head"]["root"], "checkout-api")
        self.assertTrue(x3["lens"])
        self.assertTrue(all(not r["applied"] and r["verdict"] == "not_applicable"
                            and any(not c["passed"] for c in r["checks"]) for r in x3["lens"]))

        mem = self.demo.memory()
        self.assertEqual(sorted(p["signature"] for p in mem["playbooks"]),
                         ["bad_deploy:service", "db_saturation:postgres"])
        db = next(p for p in mem["playbooks"] if p["signature"] == "db_saturation:postgres")
        self.assertEqual(db["helped"], 1)
        self.assertTrue(db["preconditions"] and db["steps"])
        approved = [f for f in mem["facts"] if f["source"] == "human" and not f["valid_to"]]
        self.assertEqual(sorted(f["value"] for f in approved), ["raw_logs", "ticket"])
        self.assertTrue(all(f["said"] and f["learned_in"] for f in approved))
        self.assertIn("Incident", self.demo.recap(x1["head"]["id"]))
        feed = self.demo.incidents()
        self.assertEqual([i["applied"] > 0 for i in feed], [False, True, False])  # newest first

    def test_wrong_playbook_misleads_twice_then_retires(self):
        pid = self.demo.plant_wrong_memory()
        results = []
        for _ in range(3):
            x = self.finish(self.demo.break_node("redis-cache"), self.investigator("inv-1"))
            planted = [r for r in x["lens"] if r["memory"] == pid]
            results.append((x["head"]["root"], [(r["verdict"], r["status"]) for r in planted]))
        self.assertEqual(results[0], ("postgres-orders", [("misled", "active")]))
        self.assertEqual(results[1], ("postgres-orders", [("misled", "retired")]))
        self.assertEqual(results[2], ("redis-cache", []))
        self.assertFalse(any(p["signature"] == "db_saturation:postgres"
                             for p in self.demo.memory()["playbooks"]),
                         "a real lesson is never filed under the planted playbook")

    def test_armed_kill_fires_once_after_the_step(self):
        class Proc:
            def __init__(self) -> None:
                self.up = True

            def alive(self) -> bool:
                return self.up

        class FakeSupervisor:
            def __init__(self) -> None:
                self.procs = {"inv-1": Proc(), "inv-2": Proc()}
                self.killed: list[str] = []

            def kill(self, name: str) -> None:
                self.killed.append(name)
                self.procs[name].up = False

        sup = FakeSupervisor()
        self.demo.supervisor = sup
        self.demo.arm_kill(2)
        key = self.demo.run_story("s01")
        inv = self.investigator("inv-1")
        fired: list[str | None] = []
        original = inv._step

        def watch(*a: Any, **kw: Any) -> Any:
            step = original(*a, **kw)
            fired.append(self.demo.check_armed_kill())
            if sup.killed:
                raise RuntimeError("SIGKILL")
            return step
        inv._step = watch  # type: ignore[method-assign]
        with self.assertRaises(RuntimeError):
            inv.run_once()
        self.assertEqual(fired, [None, "inv-1"])
        self.assertEqual(self.demo.last_kill, {"worker": "inv-1", "task": f"{key}:investigate",
                                               "after_step": 2})
        self.assertIsNone(self.demo.kill_after)
        self.assertIsNone(self.demo.check_armed_kill())  # one shot

    def test_a_task_that_keeps_failing_is_flagged_stuck(self):
        from coord import tasks
        key = self.demo.run_story("s01")
        for n in range(3):
            inv = self.investigator(f"inv-{n}")
            inv._step = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("crash"))  # type: ignore[method-assign]
            with self.assertRaises(RuntimeError):
                inv.run_once()
            expire_lease(self.g, f"{key}:investigate")
        self.assertFalse(self.investigator("inv-9").run_once())  # 3 attempts used: not claimable
        self.assertEqual(tasks.stuck_sweep(self.g), [f"{key}:investigate"])
        self.assertEqual(self.demo.incidents()[0]["stuck"], 1)
        x = self.demo.incident(key)
        assert x is not None
        self.assertEqual([t["status"] for t in x["tasks"]], ["stuck"])

    def test_recap_and_earlier_sessions(self):
        x1 = self.finish(self.demo.run_story("s01"), self.investigator("inv-1"))
        recap = self.demo.recap(x1["head"]["id"])
        self.assertIn("checkpointed steps by inv-1", recap)
        self.assertIn("For DB saturation", recap)
        x2 = self.finish(self.demo.run_story("s04"), self.investigator("inv-1"))
        self.assertTrue(x2["earlier"], "Priya's earlier session shows in the next incident")
        self.assertTrue(all(m["incident"] == x1["head"]["id"] for m in x2["earlier"]))

    def test_ui_never_shows_another_companys_data(self):
        from sim import world as W
        gb = self.backend(f"web_other_{type(self).__name__.lower()}")
        seed_graph(gb, "b")
        other = Demo(gb, "b", ScenarioStore(tempfile.mkdtemp()), Engineer(autopilot=True))
        resp_b, learn_b = other.agents()
        for sid in ("s01", "s04"):  # identical incident ids and services in both companies
            for demo, resp, learn, g in ((self.demo, self.responder, self.learner, self.g),
                                         (other, resp_b, learn_b, gb)):
                demo.run_story(sid)
                Investigator(g, "inv", ScenarioStore(demo.store.root)).run_once()
                resp.run_once()
                learn.run_once()
        api = TestClient(create_app(self.demo))
        seen = [api.get(p).text for p in ("/api/state", "/api/memory", "/api/map", "/api/db",
                                          "/api/settings")]
        for i in api.get("/api/state").json()["incidents"]:
            seen.append(api.get(f"/api/incident/{i['key']}").text)
            seen.append(api.get(f"/api/recap/{i['id']}").text)
        text = "\n".join(seen)
        markers = [W.CANARY["b"], *(full for full, _ in W.PEOPLE["b"].values())]
        self.assertEqual([m for m in markers if m in text], [])
        # and company A's own memory is there: its incidents and Priya's ticket preference
        self.assertEqual(len(api.get("/api/state").json()["incidents"]), 2)
        facts = api.get("/api/memory").json()["facts"]
        self.assertIn(("priya", "ticket"), {(f["handle"], f["value"]) for f in facts})

    def test_org_changes_route_the_next_page(self):
        self.demo.hand_over("platform-data", "kabir")
        self.demo.move_owner("checkout-api", "payments")
        org = {t["team"]: t for t in self.demo.org_chart()}
        self.assertEqual(org["platform-data"]["on_call"], ["kabir"])
        self.assertIn("checkout-api", org["payments"]["owns"])
        x = self.finish(self.demo.break_node("postgres-menu"), self.investigator("inv-1"))
        self.assertEqual([a["recipient"] for a in x["actions"]], ["kabir"])
        with self.assertRaises(ValueError):
            self.demo.break_node("kafka-events")

    def test_http_api(self):
        api = TestClient(create_app(self.demo))
        self.assertIn("Blast Radius", api.get("/").text)
        self.assertIn("Blast Radius", api.get("/classic").text)
        for path in ("/mission-control", "/war-room", "/dark", "/static/core.js", "/static/v2.css", "/static/example.json"):
            self.assertEqual(api.get(path).status_code, 200, path)
        self.assertEqual(api.get("/static/app.py").status_code, 404)
        self.assertIn("Teaching on-call agents", api.get("/blog/").text)
        for path in ("/blog/assets/core.js", "/blog/media/takeover.mp4", "/blog/assets/fonts/inter-400.woff2"):
            self.assertEqual(api.get(path).status_code, 200, path)
        for bad in ("/blog/../web/app.py", "/blog/assets/..%2F..%2F..%2F.env", "/blog/index.md"):
            self.assertEqual(api.get(bad).status_code, 404, bad)
        font = api.get("/fonts/inter-400.woff2")
        self.assertEqual((font.status_code, font.headers["content-type"]), (200, "font/woff2"))
        self.assertEqual(api.get("/fonts/..%2Fapp.py").status_code, 404)
        self.assertEqual(api.get("/api/settings").json()["company"], "a")
        self.assertEqual(api.post("/api/break", json={"node": "nope"}).status_code, 400)
        key = api.post("/api/break", json={"story": "s02"}).json()["key"]
        self.assertEqual(api.get("/api/state").json()["incidents"][0]["key"], key)
        self.assertEqual(api.get(f"/api/incident/{key}").json()["head"]["status"], "open")
        self.assertEqual(api.get("/api/incident/incident:none").status_code, 404)
        self.assertEqual(len(api.get("/api/map").json()["nodes"]), 15)
        self.assertEqual(api.post("/api/workers/inv-1/kill").status_code, 404)  # no supervisor
        self.assertIn("playbooks", api.get("/api/memory").json())
        self.assertFalse(api.post("/api/autopilot", json={"on": False}).json()["on"])
        self.assertFalse(api.post(f"/api/review/{key}", json={"confirmed": True}).json()["ok"])
        self.assertIn("MATCH", api.get("/api/cypher", params={"path": "web/queries/lens.cypher"}).json()["text"])
        for bad in ("../.env", "web/queries/../../.env", "web/app.py", "web/queries/nope.cypher"):
            self.assertEqual(api.get("/api/cypher", params={"path": bad}).status_code, 404, bad)
        db = api.get("/api/db").json()
        self.assertGreater(db["nodes"], 15)
        self.assertGreater(db["edges"], 20)
        stats = api.get(f"/api/incident/{key}").json()["db"]
        self.assertGreaterEqual(stats["queries"], 6)  # 7 once there is a root


class OutageTests(unittest.TestCase):
    def test_api_says_503_while_falkordb_is_down(self):
        from redis.exceptions import BusyLoadingError

        class Down:
            def query(self, *a: Any, **kw: Any) -> Any:
                raise BusyLoadingError("Redis is loading the dataset in memory")

        demo = Demo(Down(), "a", ScenarioStore(tempfile.mkdtemp()), Engineer())
        r = TestClient(create_app(demo)).get("/api/state")
        self.assertEqual(r.status_code, 503)
        self.assertTrue(r.json()["db_down"])


class WebOnDouble(WebCases, unittest.TestCase):
    backend = staticmethod(double)

    def test_every_web_query_was_exercised(self):
        self.test_story_through_every_panel()
        self.demo.org_chart()
        self.demo.service_map()
        self.demo.plant_wrong_memory()
        self.demo.break_node("redis-cache")
        self.demo.db_info()
        web = {q for q in GraphDouble._query_files().values() if q.startswith("web/")}
        self.assertEqual(web - GraphDouble.exercised, set())


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class WebOnFalkorDB(WebCases, unittest.TestCase):
    backend = staticmethod(falkordb)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class ReadyTests(unittest.TestCase):
    def test_ready_when_up(self):
        from common.db import wait_ready
        self.assertTrue(wait_ready(timeout_s=2, log=lambda _: None))


class ResultsTests(unittest.TestCase):
    def test_reads_newest_model_run(self):
        import json
        from pathlib import Path
        root = Path(tempfile.mkdtemp())
        for name, arms in (("2026-01-01-rule-based", ["A", "B", "C"]), ("2026-01-02-m", ["A", "C"]),
                           ("2026-01-03-m", ["C"])):
            d = root / "eval" / "results" / name
            d.mkdir(parents=True)
            (d / "summary.json").write_text(json.dumps({"meta": {"arms": arms}, "summary": {}}))
        self.assertEqual(latest_results(root)["eval"]["name"], "2026-01-02-m")
        bad = root / "eval" / "results" / "2026-01-04-m"  # newer, but the model never answered
        bad.mkdir()
        (bad / "summary.json").write_text(json.dumps(
            {"meta": {"arms": ["A", "B", "C"], "invalid": "no model"}, "summary": {}}))
        self.assertEqual(latest_results(root)["eval"]["name"], "2026-01-02-m")
        self.assertIsNone(latest_results(root)["load"])


if __name__ == "__main__":
    unittest.main()
