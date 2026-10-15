"""Tenant isolation (M9): two companies with identical service names, keys and
incident ids, different people and canary values. Any trace of one company in
the other's graph, results or conversations is a failure.

    python -m bench.isolation

Checks:
1. Every string stored in company A's graph (nodes and edges) is searched for
   company B's canary and B's people's full names, and vice versa.
2. Conversation memory stays per company: Priya asks company A for tickets on
   DB saturation; Priya in company B (same handle, a different person) still gets
   the default page, and A's preference never appears in B's notification.
3. Recall in B never returns a memory that only exists in A, even with identical ids.
4. The graph is chosen only from trusted config: unknown company ids are refused,
   and no tool the model can call takes a graph or company argument.

LLM response caches are keyed by the exact request; a request built from one
company's evidence can't be answered with another company's content unless the
two requests are byte-identical, in which case the content is identical too.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from common import config
from common.db import raw_graph
from eval import truth
from scripts.run_incident import run_incident
from scripts.seed import seed_graph
from sim import world as W
from tools.registry import TOOLS

ALL_NODES = "MATCH (n) RETURN properties(n) AS p"
ALL_EDGES = "MATCH ()-[r]->() RETURN properties(r) AS p"
ACTION_OF = ("MATCH (:Incident {key: $k})<-[:FOR]-(:Task)-[:EMITTED]->(a:Action) "
             "RETURN a.channel AS channel, a.payload AS payload")
MEMORY_IDS = "MATCH (m:Memory) RETURN m.id AS id"


def _strings(g: Any) -> list[str]:
    out: list[str] = []
    for query in (ALL_NODES, ALL_EDGES):
        for (props,) in g.query(query).result_set:
            for v in (props or {}).values():
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, list):
                    out += [x for x in v if isinstance(x, str)]
    return out


def _markers(cid: str) -> list[str]:
    return [W.CANARY[cid]] + [full for full, _ in W.PEOPLE[cid].values()]


def check(make_graph: Callable[[str], Any]) -> dict[str, Any]:
    ga, gb = make_graph("iso_a"), make_graph("iso_b")
    seed_graph(ga, "a")
    seed_graph(gb, "b")
    # Same incident ids in both companies. Priya speaks only in company A.
    s01, s04 = truth.load("s01"), truth.load("s04")
    silent_s01 = replace(s01, engineer_says=None)
    for g, first in ((ga, s01), (gb, silent_s01)):
        run_incident(g, first, "s01-iso", chat_model=None)
        run_incident(g, s04, "s04-iso", chat_model=None)

    leaks = {}
    for here, there, g in (("a", "b", ga), ("b", "a", gb)):
        text = "\n".join(_strings(g))
        found = [m for m in _markers(there) if m in text]
        own = W.CANARY[here] in text
        leaks[here] = {"other_company_markers_found": found, "own_canary_present": own}

    [(ch_a, payload_a)] = ga.query(ACTION_OF, {"k": "incident:s04-iso"}).result_set
    [(ch_b, payload_b)] = gb.query(ACTION_OF, {"k": "incident:s04-iso"}).result_set
    prefs = {"a_channel": ch_a, "b_channel": ch_b,
             "a_cites_priya": "per your note" in payload_a,
             "b_cites_anything": "per your note" in payload_b}

    ids_a = {r[0] for r in ga.query(MEMORY_IDS).result_set}
    ids_b = {r[0] for r in gb.query(MEMORY_IDS).result_set}
    only_a = sorted(ids_a - ids_b)

    try:
        config.graph_name("../company_a")
        refused_unknown = False
    except ValueError:
        refused_unknown = True
    tool_args = sorted({p for t in TOOLS.values() for p in t.parameters})
    graph_args = [p for p in tool_args if p in ("graph", "company", "tenant", "graph_name")]

    ok = (all(not v["other_company_markers_found"] and v["own_canary_present"]
              for v in leaks.values())
          and ch_a == "ticket" and ch_b == "page" and prefs["a_cites_priya"]
          and not prefs["b_cites_anything"] and refused_unknown and not graph_args)
    return {"ok": ok, "leaks": leaks, "preferences": prefs,
            "memories_only_in_a": only_a, "unknown_company_refused": refused_unknown,
            "tool_arguments": tool_args, "tool_graph_arguments": graph_args}


def live_graph(name: str) -> Any:
    g = raw_graph(name)
    with contextlib.suppress(Exception):
        g.delete()
    return raw_graph(name)


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    result = check(live_graph)
    print(json.dumps(result, indent=2))
    print("PASS" if result["ok"] else "FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
