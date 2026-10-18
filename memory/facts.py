"""Semantic memory writes (plan, A3): facts change by supersession, never by edit.

Two steps: validate (read-only), then one idempotent write. A retry with the same
payload is `already_done`; a different payload under the same id is a conflict.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from common.db import run
from memory.feedback import PRIORS

Q = "memory/queries/"


class FactConflict(ValueError):
    pass


@dataclass(frozen=True)
class FactWrite:
    id: str
    lineage: str
    subject: str            # scope node key, e.g. person:priya
    predicate: str
    object: str
    condition_family: str | None
    source_key: str         # the Message or Incident it was learned from
    source_kind: str        # "human" (approved) | "agent"
    approved_by: str | None
    valid_from: int

    def payload_hash(self) -> str:
        body = [self.subject, self.predicate, self.object, self.condition_family,
                self.source_key, self.valid_from]
        return hashlib.sha256(json.dumps(body).encode()).hexdigest()[:16]


def write(graph: Any, fact: FactWrite, scenario_now: int) -> str:
    """Write a fact version; returns "ok" or "already_done"."""
    check = run(graph, Q + "fact_check.cypher", {
        "scope_key": fact.subject, "source_key": fact.source_key,
        "id": fact.id, "lineage": fact.lineage,
    })[0]
    if not check["scope_ok"] or not check["source_ok"]:
        raise LookupError(f"{fact.id}: scope {fact.subject} or source {fact.source_key} missing")
    digest = fact.payload_hash()
    if check["existing_hash"] is not None:
        if check["existing_hash"] != digest:
            raise FactConflict(f"{fact.id} already exists with different content")
        return "already_done"

    a, b = PRIORS["human" if fact.source_kind == "human" else "agent"]
    run(graph, Q + "fact_supersede.cypher", {
        "scope_key": fact.subject, "source_key": fact.source_key, "id": fact.id,
        "lineage": fact.lineage, "version": int(check["versions"]) + 1,
        "s": fact.subject, "p": fact.predicate, "cond": fact.condition_family, "o": fact.object,
        "source_kind": fact.source_kind, "approver": fact.approved_by,
        "valid_from": fact.valid_from, "scenario_now": scenario_now,
        "a": a, "b": b, "hash": digest,
    })
    return "ok"


def retract(graph: Any, ids: list[str], at: int) -> list[str]:
    """Close agent readings the engineer did not confirm (valid_to = `at`).

    Only agent-sourced versions are closed; nothing is deleted or rewritten.
    Returns the ids closed (empty on a retry)."""
    return [r["id"] for r in run(graph, Q + "fact_retract.cypher", {"ids": ids, "at": at})]
