"""The LLM planner's guardrail, offline, with scripted model replies."""
from __future__ import annotations

import unittest

from agents.contracts import Call, Diagnosis, Step
from agents.llm_planner import GuardedLLMPlanner
from agents.planning import RuleBasedPlanner
from common.llm import LLMError, Reply, ToolCall

ALERTING = ["cart-svc", "checkout-api", "web-gateway"]


class Scripted:
    """Returns the queued replies in order; raises if told to."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen_tools = None

    def chat(self, messages, tools=None, json_mode=False):
        self.seen_tools = tools
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def call(name, **args) -> Reply:
    return Reply("", [ToolCall(name, args)])


HISTORY = [
    Step(1, "find_upstream_candidates", {"alerting": ALERTING},
         [{"name": "postgres-orders", "label": "Datastore", "hits": 3, "hops": 1}]),
    Step(2, "inspect_metrics", {"node": "postgres-orders"}, {"db_connections_pct": [40, 98]}),
]


class GuardedPlannerTests(unittest.TestCase):
    def fallback(self, history):
        return RuleBasedPlanner().next(ALERTING, history)

    def test_accepts_a_valid_new_tool_call(self):
        planner = GuardedLLMPlanner(Scripted(call("inspect_logs", node="postgres-orders")))
        self.assertEqual(planner.next(ALERTING, HISTORY),
                         Call("inspect_logs", {"node": "postgres-orders"}))
        self.assertEqual(planner.fallbacks, 0)

    def test_offers_every_registry_tool_plus_diagnosis(self):
        model = Scripted(call("inspect_logs", node="x"))
        GuardedLLMPlanner(model).next(ALERTING, [])
        names = {t["function"]["name"] for t in model.seen_tools}
        self.assertIn("submit_diagnosis", names)
        self.assertIn("find_upstream_candidates", names)

    def test_falls_back_on_anything_invalid(self):
        bad = [
            Reply("I think it's the database."),                       # no tool call
            call("drop_tables"),                                         # unknown tool
            call("inspect_metrics", node="x", graph="company_b"),       # tenant argument
            call("inspect_metrics", node="postgres-orders"),            # repeat of step 2
            call("submit_diagnosis", root="mars-db", family="db_saturation", summary="?"),
            call("submit_diagnosis", root="postgres-orders", family="gremlins", summary="?"),
            LLMError("timeout"),
        ]
        for reply in bad:
            with self.subTest(reply=reply):
                planner = GuardedLLMPlanner(Scripted(reply))
                self.assertEqual(planner.next(ALERTING, HISTORY), self.fallback(HISTORY))
                self.assertEqual(planner.fallbacks, 1)

    def test_accepts_a_grounded_diagnosis(self):
        planner = GuardedLLMPlanner(Scripted(call(
            "submit_diagnosis", root="postgres-orders", family="db_saturation",
            summary="connections at 98%", evidence_steps=[2, 99])))
        move = planner.next(ALERTING, HISTORY)
        self.assertEqual(move, Diagnosis("postgres-orders", "db_saturation",
                                         "connections at 98%", (2,)))

    def test_refuses_to_diagnose_without_evidence(self):
        planner = GuardedLLMPlanner(Scripted(call(
            "submit_diagnosis", root="cart-svc", family="bad_deploy", summary="hunch")))
        self.assertIsInstance(planner.next(ALERTING, []), Call)
        self.assertEqual(planner.fallbacks, 1)


if __name__ == "__main__":
    unittest.main()
