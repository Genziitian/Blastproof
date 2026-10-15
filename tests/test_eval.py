"""The benchmark itself: scenario definitions, and a full run of arms A and C.

Runs on the graph double always and on FalkorDB when it is up, with the
deterministic planner, so the scenario design and the scorer are checked without
spending a model call.
"""
from __future__ import annotations

import json
import unittest
from collections import Counter
from typing import Any

from eval import scenarios
from eval.run import markdown, run_eval
from tests.backends import SKIP_REASON, double, falkordb, falkordb_up


class ScenarioDefinitionTests(unittest.TestCase):
    def test_committed_truth_files_match_the_definition(self):
        for row in scenarios.timeline() + scenarios.m5():
            with self.subTest(id=row["id"]):
                on_disk = json.loads((scenarios.TRUTH_DIR / f"{row['id']}.json").read_text())
                self.assertEqual(on_disk, row, "run: python -m eval.scenarios --write")

    def test_category_sizes_follow_the_plan(self):
        counts = Counter(r["category"] for r in scenarios.timeline())
        self.assertEqual(counts, {"cold": 6, "repeat": 6, "related": 6, "same": 6,
                                  "novel": 3, "org": 3})

    def test_repeats_use_wording_never_seen_for_that_root(self):
        seen: dict[str, set[int]] = {}
        for r in scenarios.timeline():
            if r["category"] == "repeat":
                self.assertNotIn(r["wording"], seen.get(r["root"], set()), r["id"])
            seen.setdefault(r["root"], set()).add(r["wording"])

    def test_time_runs_forward(self):
        onsets = [r["onset"] for r in scenarios.timeline()]
        self.assertEqual(onsets, sorted(onsets))


class EvalCases:
    backend: Any
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    m5: dict[str, Any] | None

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.summary, cls.m5 = run_eval(
            ["A", "B", "C"], lambda name: cls.backend(f"test_{name}"), lambda: None,
            log=lambda _: None)

    def test_every_incident_is_diagnosed_and_routed_correctly(self):
        for r in self.rows:
            with self.subTest(arm=r["arm"], id=r["id"]):
                self.assertTrue(r["correct"], (r["diagnosis_root"], r["diagnosis_family"]))
                self.assertTrue(r["recipient_ok"], (r["recipient"], r["expected_recipient"]))
                self.assertTrue(r["channel_ok"], (r["channel"], r["expected_channel"]))
                self.assertEqual(r["notifications"], 1)

    def test_memory_never_misleads_and_novel_cases_force_nothing(self):
        c = [r for r in self.rows if r["arm"] == "C"]
        self.assertFalse(any(r["misled"] for r in c))
        self.assertFalse(any(r["memory_applied"] for r in c if r["category"] in ("cold", "novel")))

    def test_graph_memory_cuts_work_on_repeats(self):
        s = self.summary
        self.assertLess(s["C"]["repeat"]["mean_steps"], s["A"]["repeat"]["mean_steps"])
        self.assertTrue(all(r["helped"] for r in self.rows
                            if r["arm"] == "C" and r["category"] in ("repeat", "related")))

    def test_text_memory_never_misleads_either(self):
        b = [r for r in self.rows if r["arm"] == "B"]
        self.assertEqual(len(b), 30)
        self.assertFalse(any(r["misled"] for r in b))

    def test_recall_at_5_is_measured_on_the_same_snapshot(self):
        m2 = self.summary["m2"]
        self.assertGreater(m2["n"], 10)
        self.assertEqual(m2["graph_recall_at_5"], 1.0)
        self.assertLessEqual(m2["text_recall_at_5"], m2["graph_recall_at_5"])

    def test_m5_wrong_playbook_misleads_twice_then_retires(self):
        assert self.m5 is not None
        self.assertEqual(self.m5["misleading_uses_before_retirement"], 2)
        self.assertEqual(self.m5["retired_after_incident"], 2)
        self.assertTrue(self.m5["correct_after_retirement"])

    def test_report_renders(self):
        text = markdown(self.summary, self.m5, {"name": "t", "model": "rule-based",
                                                "at": "-", "cached": False})
        self.assertIn("Misleading uses before retirement: **2**", text)


class PartialSaveTests(unittest.TestCase):
    def test_each_row_is_handed_over_as_soon_as_it_is_scored(self):
        seen: list[str] = []
        _, _, m5 = run_eval(["A"], lambda n: double(f"partial_{n}"), lambda: None,
                            only=["e01", "e02"], log=lambda _: None,
                            on_row=lambda r: seen.append(r["id"]))
        self.assertEqual(seen, ["e01", "e02"])
        self.assertIsNone(m5)


class EvalOnDouble(EvalCases, unittest.TestCase):
    backend = staticmethod(double)


@unittest.skipUnless(falkordb_up(), SKIP_REASON)
class EvalOnFalkorDB(EvalCases, unittest.TestCase):
    backend = staticmethod(falkordb)


if __name__ == "__main__":
    unittest.main()
