"""Create indexes and unique constraints, then wait until every constraint is OPERATIONAL.

Run once per company BEFORE any worker starts:
    python -m scripts.setup_schema            # all configured companies
    python -m scripts.setup_schema --company a

A unique constraint needs an exact-match index on the same property first and is
built asynchronously: https://docs.falkordb.com/commands/graph.constraint-create
"""
from __future__ import annotations

import argparse
import sys
import time

from common import config
from common.db import client, graph

# (label, property)
UNIQUE = [
    ("Memory", "id"), ("Task", "id"), ("Decision", "id"), ("Action", "key"),
    ("Feedback", "id"), ("Checkpoint", "cid"), ("Session", "id"),
    ("Service", "key"), ("Datastore", "key"), ("Team", "key"), ("Person", "key"),
    ("Incident", "key"), ("Alert", "key"), ("Message", "key"),
]
PLAIN = [
    ("Service", "name"), ("Task", "status"), ("Task", "type"),
    ("Memory", "lineage_id"), ("Playbook", "signature"), ("Incident", "status"),
]


def create_index(g, label: str, prop: str) -> None:
    try:
        g.query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        print(f"  index   {label}.{prop}")
    except Exception as e:  # already exists
        if "already" in str(e).lower():
            print(f"  index   {label}.{prop} (exists)")
        else:
            raise


def create_unique(gname: str, label: str, prop: str) -> None:
    try:
        reply = client().connection.execute_command(
            "GRAPH.CONSTRAINT", "CREATE", gname, "UNIQUE", "NODE", label,
            "PROPERTIES", 1, prop)
        print(f"  unique  {label}.{prop} -> {reply}")
    except Exception as e:
        if "already" in str(e).lower() or "exists" in str(e).lower():
            print(f"  unique  {label}.{prop} (exists)")
        else:
            raise


def wait_operational(g, timeout_s: int = 60) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        res = g.query("CALL db.constraints()")
        header = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
        rows = [dict(zip(header, r, strict=True)) for r in res.result_set]
        statuses = [str(r.get("status", "")).upper() for r in rows]
        if any("FAILED" in s for s in statuses):
            print("  constraint FAILED; existing data violates it:", rows)
            return False
        if rows and all("OPERATIONAL" in s for s in statuses):
            print(f"  all {len(rows)} constraints OPERATIONAL")
            return True
        time.sleep(1)
    print("  timed out waiting for constraints")
    return False


def setup(cid: str) -> bool:
    """Indexes and unique constraints for one company; True once all are OPERATIONAL."""
    gname = config.graph_name(cid)
    print(f"[{gname}]")
    g = graph(cid)
    for label, prop in UNIQUE + PLAIN:
        create_index(g, label, prop)
    for label, prop in UNIQUE:
        create_unique(gname, label, prop)
    return wait_operational(g)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", choices=config.COMPANIES)
    args = ap.parse_args()
    ok = True
    for cid in ([args.company] if args.company else config.COMPANIES):
        ok = setup(cid) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
