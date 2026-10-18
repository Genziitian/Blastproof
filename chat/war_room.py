"""The war room: where the on-call engineer and the responder talk.

Every turn is stored verbatim as a Message in a Session (per engineer, per
incident). Instructions in the engineer's words become conditional preference
facts sourced to the exact message, after the responder reads them back. In a
later session, possibly after a full restart, the responder loads the
preferences that match the new incident and cites where each came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from chat.preferences import Preference, extract, readback
from common.db import run
from common.llm import ChatModel
from memory import facts

Q = "chat/queries/"
DIAGNOSIS_LABELS = {"db_saturation": "database saturation", "bad_deploy": "a bad deploy",
                    "cache_failure": "a cache failure"}
AFFIRMATIVE = re.compile(r"\s*(yes|yep|yeah|correct|right|confirmed|that's right|sure)\b", re.I)
# Any of these anywhere means the read-back is not approved ("Correct me if I'm
# wrong, but no"). Saving nothing is the safe side: the engineer can say it again.
DISSENT = re.compile(r"\b(no|not|nope|wrong|incorrect|don'?t|isn'?t|never)\b", re.I)


def affirms(reply: str | None) -> bool:
    if not reply:
        return False
    reply = reply.replace("\u2019", "'")
    return bool(AFFIRMATIVE.match(reply)) and not DISSENT.search(reply)


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

    @staticmethod
    def _fact_ids(message_key: str, prefs: list[Preference],
                  version_key: str | None = None) -> list[str]:
        version = (version_key or message_key).removeprefix("message:")
        return [f"fact:{version}:{i}" for i in range(len(prefs))]

    def remember(self, handle: str, message_key: str, prefs: list[Preference],
                 approved_by: str | None, scenario_now: int,
                 version_key: str | None = None, valid_from: int | None = None) -> None:
        """Write each preference as a fact sourced to the message it came from.

        Unconfirmed, it is the agent's reading (agent prior). Once the engineer
        confirms the read-back, a human-approved version supersedes it (A3), still
        sourced to the engineer's own words; `version_key` names that version.
        """
        ids = self._fact_ids(message_key, prefs, version_key)
        for fact_id, pref in zip(ids, prefs, strict=True):
            facts.write(self.graph, facts.FactWrite(
                id=fact_id,
                lineage=pref.lineage(person_key(handle)),
                subject=person_key(handle),
                predicate=pref.predicate,
                object=pref.value,
                condition_family=pref.condition_family,
                source_key=message_key,
                source_kind="human" if approved_by else "agent",
                approved_by=approved_by,
                valid_from=scenario_now if valid_from is None else valid_from,
            ), scenario_now)

    def forget_reading(self, message_key: str, prefs: list[Preference], at: int) -> list[str]:
        """The engineer did not confirm the read-back: close the agent's reading."""
        return facts.retract(self.graph, self._fact_ids(message_key, prefs), at)

    def preferences(self, handle: str, family: str, scenario_now: int) -> list[AppliedPreference]:
        rows = run(self.graph, Q + "preferences_for.cypher", {
            "person_key": person_key(handle), "family": family, "scenario_now": scenario_now,
        })
        # A preference for this family beats a general one; one the engineer
        # approved beats the agent's unconfirmed reading; then the newest wins.
        rows.sort(key=lambda r: (r["condition_family"] is None, r["source"] != "human",
                                 -int(r["recorded_at"])))
        seen: set[str] = set()
        prefs = []
        for r in rows:
            if r["predicate"] in seen:
                continue
            seen.add(r["predicate"])
            prefs.append(AppliedPreference(r["predicate"], r["value"], r["said"], r["learned_in"]))
        return prefs

    def recap(self, incident_id: str) -> str:
        """Answer "where did we leave <incident>?" from what the graph stored."""
        key = f"incident:{incident_id}"
        rows = run(self.graph, Q + "incident_recap.cypher", {"incident_key": key})
        steps = run(self.graph, Q + "incident_steps.cypher", {"incident_key": key})
        work = ""
        if steps and steps[0]["steps"]:
            s = steps[0]
            who = ", ".join(a for a in s["agents"] if a)
            took_over = " (taken over after the first worker stopped)" if (s["epochs"] or 1) > 1 else ""
            work = (f"The investigation took {s['steps']} checkpointed steps"
                    f"{' by ' + who if who else ''}{took_over}.")
        if not rows:
            gone = f"I have no conversation stored for incident {incident_id}."
            return f"{gone} {work}".strip()
        first = rows[0]
        label = DIAGNOSIS_LABELS.get(first["family"] or "", first["family"] or "unknown")
        lines = [f"Incident {incident_id}: {first['root'] or 'no diagnosis'}, {label} "
                 f"({first['status']}, verdict {first['verdict'] or 'pending'})."]
        if work:
            lines.append(work)
        for r in rows:
            who = "You" if r["role"] == "engineer" else "I"
            text = r["text"].splitlines()[0] if r["role"] == "agent" else r["text"]
            lines.append(f'{who} said: "{text}"')
        return "\n".join(lines)

    def recent(self, handle: str, limit: int = 6) -> list[dict[str, Any]]:
        return run(self.graph, Q + "recent_messages.cypher",
                   {"person_key": person_key(handle), "limit": limit})


__all__ = ["AppliedPreference", "WarRoom", "affirms", "readback"]
