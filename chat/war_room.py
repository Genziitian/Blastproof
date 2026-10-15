"""The war room: where the on-call engineer and the responder talk.

Every turn is stored verbatim as a Message in a Session (per engineer, per
incident). Instructions in the engineer's words become conditional preference
facts sourced to the exact message, after the responder reads them back. In a
later session, possibly after a full restart, the responder loads the
preferences that match the new incident and cites where each came from.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chat.preferences import Preference, extract, readback
from common.db import run
from common.llm import ChatModel
from memory import facts

Q = "chat/queries/"


@dataclass(frozen=True)
class AppliedPreference:
    predicate: str
    value: str
    said: str | None
    learned_in: str | None

    def citation(self) -> str:
        if not self.learned_in:
            return ""
        return f'per your note in incident {self.learned_in}: "{self.said}"'


def person_key(handle: str) -> str:
    return f"person:{handle}"


class WarRoom:
    def __init__(self, graph: Any, model: ChatModel | None = None) -> None:
        self.graph = graph
        self.model = model

    def open(self, incident_id: str, incident_key: str, handle: str, scenario_now: int) -> str:
        session_id = f"session:{incident_id}:{handle}"
        run(self.graph, Q + "open_session.cypher", {
            "session_id": session_id, "person_key": person_key(handle),
            "incident_key": incident_key, "scenario_now": scenario_now,
        })
        return session_id

    def say(self, session_id: str, seq: int, role: str, text: str, scenario_now: int) -> str:
        key = f"message:{session_id.removeprefix('session:')}:{seq}"
        run(self.graph, Q + "add_message.cypher", {
            "session_id": session_id, "key": key, "role": role, "text": text,
            "seq": seq, "at": scenario_now + seq,
        })
        return key

    def understand(self, text: str) -> list[Preference]:
        return extract(text, self.model)

    def remember(self, handle: str, message_key: str, prefs: list[Preference],
                 approved_by: str | None, scenario_now: int) -> None:
        """Write each preference as a fact sourced to the message it came from."""
        for i, pref in enumerate(prefs):
            facts.write(self.graph, facts.FactWrite(
                id=f"fact:{message_key.removeprefix('message:')}:{i}",
                lineage=pref.lineage(person_key(handle)),
                subject=person_key(handle),
                predicate=pref.predicate,
                object=pref.value,
                condition_family=pref.condition_family,
                source_key=message_key,
                source_kind="human" if approved_by else "agent",
                approved_by=approved_by,
                valid_from=scenario_now,
            ), scenario_now)

    def preferences(self, handle: str, family: str, scenario_now: int) -> list[AppliedPreference]:
        rows = run(self.graph, Q + "preferences_for.cypher", {
            "person_key": person_key(handle), "family": family, "scenario_now": scenario_now,
        })
        # A preference for this family beats a general one; then the newest wins.
        rows.sort(key=lambda r: (r["condition_family"] is None, -int(r["recorded_at"])))
        seen: set[str] = set()
        prefs = []
        for r in rows:
            if r["predicate"] in seen:
                continue
            seen.add(r["predicate"])
            prefs.append(AppliedPreference(r["predicate"], r["value"], r["said"], r["learned_in"]))
        return prefs

    def recent(self, handle: str, limit: int = 6) -> list[dict[str, Any]]:
        return run(self.graph, Q + "recent_messages.cypher",
                   {"person_key": person_key(handle), "limit": limit})


__all__ = ["AppliedPreference", "WarRoom", "readback"]
