"""An LLM planner with the rule-based planner as its guardrail.

The model sees the alerting services and every step so far, and answers with one
tool call: an evidence or graph tool, or `submit_diagnosis`. Any answer that is
malformed, repeats a step, names an unknown tool, cites a node it never saw, or
arrives after an error is replaced by the rule-based planner's move. The demo
gets a reasoning agent; the run can't derail.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from agents.contracts import Call, Diagnosis, Step
from agents.planning import Planner, RuleBasedPlanner
from common.llm import ChatModel, LLMError, Reply
from tools.registry import INVESTIGATOR_TOOLS as TOOLS
from tools.registry import ToolError, validate

FAMILIES = ("db_saturation", "bad_deploy", "cache_failure")
MAX_OBSERVATION_CHARS = 1500

SYSTEM = (
    "You are an on-call investigator. Find the root cause of an incident from evidence. "
    "Call exactly one tool per turn. Start broad (shared dependencies, recent changes), "
    "then confirm with metrics or logs. When one cause is clearly supported, call "
    "submit_diagnosis with the failing node, the failure family and a one-sentence summary "
    "that cites the evidence. Never repeat a call you have already made."
)

DIAGNOSE = {
    "type": "function",
    "function": {
        "name": "submit_diagnosis",
        "description": "Report the root cause once the evidence supports it.",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "Failing service or datastore"},
                "family": {"type": "string", "enum": list(FAMILIES)},
                "summary": {"type": "string"},
                "evidence_steps": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["root", "family", "summary"],
        },
    },
}


def _openai_tools() -> list[dict[str, Any]]:
    tools = [{"type": "function",
              "function": {"name": t.name, "description": t.description,
                           "parameters": t.schema()["input_schema"]}}
             for t in TOOLS.values()]
    return [*tools, DIAGNOSE]


class GuardedLLMPlanner:
    def __init__(self, model: ChatModel, fallback: Planner | None = None) -> None:
        self.model = model
        self.fallback = fallback or RuleBasedPlanner()
        self.log = logging.getLogger("planner.llm")
        self.fallbacks = 0
        self._tools = _openai_tools()

    def next(self, alerting: Sequence[str], history: Sequence[Step]) -> Call | Diagnosis:
        try:
            reply = self.model.chat(self._messages(alerting, history), tools=self._tools)
            move = self._accept(reply, alerting, history)
        except LLMError as e:
            self.log.warning("model unavailable (%s); using rule-based step", e)
            move = None
        if move is None:
            self.fallbacks += 1
            return self.fallback.next(alerting, history)
        return move

    def _messages(self, alerting: Sequence[str], history: Sequence[Step]) -> list[dict[str, Any]]:
        """One text part per step. Each turn's parts start with the previous turn's,
        so a provider with prompt caching (Claude) re-reads earlier steps from cache;
        OpenAI-compatible clients join the parts into one string."""
        head = [f"Alerting services: {', '.join(sorted(alerting))}", "", "Steps so far:"]
        if not history:
            head.append("(none)")
        parts = ["\n".join(head)]
        for s in history:
            observed = json.dumps(s.observation, sort_keys=True)[:MAX_OBSERVATION_CHARS]
            parts.append(f"{s.n}. {s.tool}({json.dumps(s.args, sort_keys=True)}) -> {observed}")
        return [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": [{"type": "text", "text": p} for p in parts]}]

    def _accept(self, reply: Reply, alerting: Sequence[str],
                history: Sequence[Step]) -> Call | Diagnosis | None:
        if len(reply.tool_calls) != 1:
            self.log.info("rejected: expected one tool call, got %d", len(reply.tool_calls))
            return None
        call = reply.tool_calls[0]
        if call.name == "submit_diagnosis":
            return self._diagnosis(call.arguments, alerting, history)
        tool = TOOLS.get(call.name)
        if tool is None:
            self.log.info("rejected: unknown tool %r", call.name)
            return None
        try:
            validate(tool, call.arguments)
        except ToolError as e:
            self.log.info("rejected: %s", e)
            return None
        if any(s.tool == call.name and s.args == call.arguments for s in history):
            self.log.info("rejected: repeats %s", call.name)
            return None
        return Call(call.name, dict(call.arguments))

    def _diagnosis(self, args: dict[str, Any], alerting: Sequence[str],
                   history: Sequence[Step]) -> Diagnosis | None:
        root, family = args.get("root"), args.get("family")
        seen = " ".join(alerting) + json.dumps([s.observation for s in history])
        if not isinstance(root, str) or not root or root not in seen:
            self.log.info("rejected: diagnosis names a node never observed (%r)", root)
            return None
        if family not in FAMILIES or len(history) < 2:
            self.log.info("rejected: diagnosis %r with %d steps of evidence", family, len(history))
            return None
        steps = tuple(n for n in args.get("evidence_steps") or ()
                      if isinstance(n, int) and 1 <= n <= len(history))
        return Diagnosis(root, family, str(args.get("summary", ""))[:300], steps)
