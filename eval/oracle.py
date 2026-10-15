"""The scripted on-call engineer used in place of a human during eval runs.

It answers through the same confirmation interface the war-room UI will use, so
the only things that reach the graph are a confirm or a reject and whatever the
scripted engineer says, never the scenario's label.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.contracts import Diagnosis, Verdict
from eval.truth import Truth


@dataclass
class Oracle:
    by: str = "oracle"

    def __post_init__(self) -> None:
        self._truth: dict[str, Truth] = {}

    def watch(self, incident_key: str, truth: Truth) -> None:
        self._truth[incident_key] = truth

    def answer(self, incident_key: str, question: str) -> str | None:
        """The scripted engineer confirms a read-back of what they asked for."""
        truth = self._truth.get(incident_key)
        return "Yes, that's right." if truth and truth.engineer_says and question else None

    def review(self, incident_key: str, diagnosis: Diagnosis) -> Verdict:
        truth = self._truth[incident_key]
        correct = diagnosis.root == truth.root and diagnosis.family == truth.family
        return Verdict(confirmed=correct, by=self.by, message=truth.engineer_says)
