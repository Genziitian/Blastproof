"""Seed the world graph for each company. An EXPLICIT command, never run on startup,
so the persistence test can't pass just because data was recreated.

    python -m scripts.seed                 # refuses if a company graph already has data
    python -m scripts.seed --reset         # deletes and reseeds (asks for confirmation)
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from common import config
from common.db import graph
from sim import world as W


def seed_graph(g: Any, cid: str) -> None:
    """Write the world for company `cid` into graph `g`."""
    t0 = W.WORLD_START_MS
    for name, (tier, cf) in W.SERVICES.items():
        g.query("CREATE (:Service {key: $k, name: $n, tier: $t, customer_facing: $cf})",
                {"k": W.key("service", name), "n": name, "t": tier, "cf": cf})
    for name, kind in W.DATASTORES.items():
        g.query("CREATE (:Datastore {key: $k, name: $n, kind: $kind})",
                {"k": W.key("datastore", name), "n": name, "kind": kind})
    for a, b in W.DEPENDS_ON:
        g.query("MATCH (x {name: $a}), (y {name: $b}) "
                "WHERE (x:Service OR x:Datastore) AND (y:Service OR y:Datastore) "
                "CREATE (x)-[:DEPENDS_ON]->(y)", {"a": a, "b": b})
    for team, (channel, owned) in W.TEAMS.items():
        g.query("CREATE (:Team {key: $k, name: $n, channel: $c})",
                {"k": W.key("team", team), "n": team, "c": channel})
        for node in owned:
            g.query("MATCH (x {name: $node}), (t:Team {name: $team}) "
                    "WHERE x:Service OR x:Datastore "
                    "CREATE (x)-[:OWNED_BY {valid_from: $t0}]->(t)",
                    {"node": node, "team": team, "t0": t0})
    on_call_given: set[str] = set()
    for handle, (full, team) in W.PEOPLE[cid].items():
        g.query("MATCH (t:Team {name: $team}) "
                "CREATE (p:Person {key: $k, handle: $h, name: $n})"
                "-[:MEMBER_OF {valid_from: $t0}]->(t)",
                {"team": team, "k": W.key("person", handle), "h": handle,
                 "n": full, "t0": t0})
        if team not in on_call_given:
            on_call_given.add(team)
            g.query("MATCH (p:Person {handle: $h}), (t:Team {name: $team}) "
                    "CREATE (p)-[:ON_CALL {valid_from: $t0}]->(t)",
                    {"h": handle, "team": team, "t0": t0})
    g.query("CREATE (:Canary {key: 'canary', value: $v})", {"v": W.CANARY[cid]})


def seed_company(cid: str) -> None:
    seed_graph(graph(cid), cid)


def node_count(cid: str) -> int:
    try:
        return graph(cid).query("MATCH (n) RETURN count(n)").result_set[0][0]
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    for cid in config.COMPANIES:
        n = node_count(cid)
        if n and not args.reset:
            print(f"company_{cid} already has {n} nodes; not reseeding (use --reset)")
            continue
        if n and args.reset:
            if input(f"Delete ALL data in company_{cid}? type yes: ") != "yes":
                print("skipped")
                continue
            graph(cid).delete()
            print(f"company_{cid} deleted; run scripts.setup_schema again before workers start")
        seed_company(cid)
        print(f"company_{cid} seeded: {node_count(cid)} nodes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
