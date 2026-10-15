"""Org changes in the simulated company: on-call handovers and ownership moves.

The same close-and-open pattern as facts (plan, A3): the old edge gets a valid_to,
the new one a valid_from, nothing is deleted, so `who_to_page` answers correctly
for any moment, before or after the change.
"""
from __future__ import annotations

from typing import Any

from common.db import run

Q = "sim/queries/"


def hand_over_on_call(graph: Any, team: str, person: str, at_ms: int) -> None:
    run(graph, Q + "close_on_call.cypher", {"team": team, "at": at_ms})
    run(graph, Q + "open_on_call.cypher", {"handle": person, "team": team, "at": at_ms})


def move_ownership(graph: Any, node: str, team: str, at_ms: int) -> None:
    run(graph, Q + "close_owner.cypher", {"node": node, "at": at_ms})
    run(graph, Q + "open_owner.cypher", {"node": node, "team": team, "at": at_ms})
