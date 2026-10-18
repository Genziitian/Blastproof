"""Turning what an engineer says into conditional preference facts.

"For DB saturation, open a ticket and paste the raw slow-query lines" becomes
two facts, both conditioned on the failure family:

    preferred_channel = ticket     (when family = db_saturation)
    wants_detail      = raw_logs   (when family = db_saturation)

The condition is part of the fact's lineage, so "for bad deploys, page me" sits
beside it instead of replacing it. A configured LLM does the parsing; without
one, or if its answer doesn't fit the vocabulary, a deterministic parser does.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from common.llm import ChatModel, LLMError

CHANNELS = ("ticket", "page", "slack")
DETAILS = ("raw_logs", "summary")
FAMILY_LABELS = {
    "db_saturation": "DB saturation",
    "bad_deploy": "bad deploys",
    "cache_failure": "cache failures",
}
_FAMILY_WORDS = {
    "db_saturation": ("db saturation", "database saturation", "connection pool", "db saturated",
                      "database is saturated", "too many connections"),
    "bad_deploy": ("bad deploy", "bad release", "deploy", "release"),
    "cache_failure": ("cache",),
}
_NEGATION = r"(?:don'?t|do not|never|no|not|stop)\b[^.,;]{0,25}"


@dataclass(frozen=True)
class Preference:
    predicate: str                  # "preferred_channel" | "wants_detail"
    value: str
    condition_family: str | None    # None = applies to every incident

    def lineage(self, person_key: str) -> str:
        return f"{person_key}|{self.predicate}|{self.condition_family or '*'}"

    def readback(self) -> str:
        when = f"for {FAMILY_LABELS[self.condition_family]}" if self.condition_family else "always"
        if self.predicate == "preferred_channel":
            return f"{when}, notify you by {self.value}"
        return f"{when}, include {'raw log lines' if self.value == 'raw_logs' else 'a summary'}"


def readback(prefs: list[Preference]) -> str:
    return "Saved: " + "; ".join(p.readback() for p in prefs) + ". Correct?"


def _mentioned(text: str, word: str) -> bool:
    return re.search(rf"\b{word}", text) is not None


def _negated(text: str, word: str) -> bool:
    return re.search(rf"{_NEGATION}{word}", text) is not None


def parse_rules(text: str) -> list[Preference]:
    # Curly apostrophes (phones, docs) would hide "don't" from the negation check.
    t = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    family = next((f for f, words in _FAMILY_WORDS.items() if any(w in t for w in words)), None)
    prefs = []

    channel = None
    if _mentioned(t, "ticket") and not _negated(t, "ticket"):
        channel = "ticket"
    elif re.search(r"\b(page|call) me\b", t) and not _negated(t, "(?:page|call)"):
        channel = "page"
    elif _mentioned(t, "slack") and not _negated(t, "(?:ping me on )?slack"):
        channel = "slack"
    if channel:
        prefs.append(Preference("preferred_channel", channel, family))

    # Raw lines win when asked for ("raw logs and a summary"), but a negated request
    # is never saved as the thing it negates ("do not paste raw logs, just a summary").
    if ("raw" in t and re.search(r"\b(log|lines|quer)", t)
            and not _negated(t, r"(?:\w+ )?raw")):
        prefs.append(Preference("wants_detail", "raw_logs", family))
    elif _mentioned(t, "summary") and not _negated(t, r"(?:\w+ )?summary"):
        prefs.append(Preference("wants_detail", "summary", family))
    return prefs


_PROMPT = (
    "Extract notification preferences from an on-call engineer's message. Reply with JSON: "
    '{"preferences": [{"predicate": "preferred_channel" | "wants_detail", '
    '"value": one of ' + json.dumps(list(CHANNELS)) + " for preferred_channel or "
    + json.dumps(list(DETAILS)) + ' for wants_detail, "condition_family": one of '
    + json.dumps(list(FAMILY_LABELS)) + " or null if it applies to every incident}]}. "
    "Only include what the engineer actually asked for."
)


def parse_with_model(model: ChatModel, text: str) -> list[Preference] | None:
    try:
        reply = model.chat([{"role": "system", "content": _PROMPT},
                            {"role": "user", "content": text}], json_mode=True)
        items = json.loads(reply.content).get("preferences", [])
    except (LLMError, json.JSONDecodeError, AttributeError):
        return None
    prefs = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            return None
        predicate, value = item.get("predicate"), item.get("value")
        family = item.get("condition_family")
        allowed = CHANNELS if predicate == "preferred_channel" else DETAILS
        if predicate not in ("preferred_channel", "wants_detail") or value not in allowed:
            return None
        if family is not None and family not in FAMILY_LABELS:
            return None
        prefs.append(Preference(str(predicate), str(value), family))
    return prefs


def extract(text: str, model: ChatModel | None = None) -> list[Preference]:
    if model is not None:
        parsed = parse_with_model(model, text)
        if parsed is not None:
            return parsed
    return parse_rules(text)
