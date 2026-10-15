"""The on-call engineer, played by whoever is at the UI.

The responder calls `review()` (confirm or reject the diagnosis, optionally say
something) and `answer()` (reply to the read-back of what it understood). Each call
waits until the person answers in the war room. With autopilot on, or if nobody
answers within `timeout_s`, the scripted engineer answers instead: it confirms a
correct diagnosis and says the scenario's scripted line, exactly like the eval oracle.

Only what the engineer says, and their confirm or reject, ever reaches the graph.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from agents.contracts import Diagnosis, Verdict


class Cancelled(RuntimeError):
    """The UI was reset while the responder was waiting."""


@dataclass
class Script:
    """What the scripted engineer knows about an incident (evaluator side only)."""

    root: str
    family: str
    says: str | None = None


@dataclass
class Pending:
    incident_key: str
    kind: str                      # "review" | "readback"
    prompt: dict[str, Any]
    suggestion: str | None
    since: float = field(default_factory=time.time)
    reply: Any = None
    done: threading.Event = field(default_factory=threading.Event)

    def view(self) -> dict[str, Any]:
        return {"incident_key": self.incident_key, "kind": self.kind, "prompt": self.prompt,
                "suggestion": self.suggestion, "waiting_s": round(time.time() - self.since, 1)}


class Engineer:
    def __init__(self, autopilot: bool = False, timeout_s: float = 600.0,
                 handle_for: Any = None) -> None:
        self.autopilot = autopilot
        self.timeout_s = timeout_s
        self.handle_for = handle_for or (lambda key: None)  # who was notified
        self._scripts: dict[str, Script] = {}
        self._pending: dict[str, Pending] = {}
        self._lock = threading.Lock()
        self._epoch = 0

    # -- set up by the UI when it starts an incident
    def watch(self, incident_key: str, script: Script) -> None:
        with self._lock:
            self._scripts[incident_key] = script

    # -- Confirmer protocol (called by the responder thread)
    def review(self, incident_key: str, diagnosis: Diagnosis) -> Verdict:
        by = self.handle_for(incident_key) or "on-call"
        script = self._scripts.get(incident_key)
        scripted = Verdict(
            confirmed=bool(script and (diagnosis.root, diagnosis.family)
                           == (script.root, script.family)) if script else True,
            by=by, message=script.says if script else None)
        reply = self._wait(incident_key, "review", diagnosis.as_dict(),
                           script.says if script else None)
        if reply is None:
            return scripted
        return Verdict(confirmed=bool(reply["confirmed"]), by=by,
                       message=(reply.get("message") or "").strip() or None)

    def answer(self, incident_key: str, question: str) -> str | None:
        reply = self._wait(incident_key, "readback", {"question": question},
                           "Yes, that's right.")
        if reply is None:
            return "Yes, that's right."
        text: str = (reply.get("text") or "").strip()
        return text or None

    # -- called by the UI
    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [p.view() for p in self._pending.values()]

    def submit(self, incident_key: str, reply: dict[str, Any]) -> bool:
        with self._lock:
            p = self._pending.get(incident_key)
            if p is None:
                return False
            p.reply = reply
        p.done.set()
        return True

    def cancel_all(self) -> None:
        with self._lock:
            self._epoch += 1
            waiting = list(self._pending.values())
            self._pending.clear()
            self._scripts.clear()
        for p in waiting:
            p.reply = Cancelled
            p.done.set()

    # -- internals
    def _wait(self, key: str, kind: str, prompt: dict[str, Any],
              suggestion: str | None) -> dict[str, Any] | None:
        """The person's reply, or None to let the scripted engineer answer."""
        if self.autopilot:
            return None
        p = Pending(key, kind, prompt, suggestion)
        with self._lock:
            self._pending[key] = p
        deadline = time.time() + self.timeout_s
        try:
            while not p.done.wait(0.25):
                if self.autopilot or time.time() > deadline:
                    return None
        finally:
            with self._lock:
                if self._pending.get(key) is p:
                    del self._pending[key]
        if p.reply is Cancelled:
            raise Cancelled(key)
        reply: dict[str, Any] = p.reply
        return reply
