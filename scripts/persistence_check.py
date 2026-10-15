"""Prove data survives a restart without being reseeded.

    python -m scripts.persistence_check write     # before restarting
    docker compose down && docker compose up -d
    python -m scripts.persistence_check verify    # after

From Gate G2 on, `verify` also requires at least one Incident, Checkpoint,
preference Fact and Playbook created AFTER seeding (pass --full).
"""
from __future__ import annotations

import argparse
import sys
import uuid

from common import config
from common.db import graph


def write() -> int:
    for cid in config.COMPANIES:
        token = uuid.uuid4().hex[:8]
        graph(cid).query("MERGE (m:PersistenceMarker {key: 'persist'}) "
                         "SET m.token = $t, m.at = timestamp()", {"t": token})
        print(f"company_{cid}: marker {token} written")
    return 0


def verify(full: bool) -> int:
    ok = True
    for cid in config.COMPANIES:
        g = graph(cid)
        rows = g.query("MATCH (m:PersistenceMarker {key: 'persist'}) RETURN m.token").result_set
        print(f"company_{cid}: marker {'found ' + rows[0][0] if rows else 'MISSING'}")
        ok &= bool(rows)
        if full:
            for label, q in [
                ("incident", "MATCH (n:Incident) RETURN count(n)"),
                ("checkpoint", "MATCH (n:Checkpoint) RETURN count(n)"),
                ("preference", "MATCH (n:Memory:Fact) WHERE n.predicate STARTS WITH 'preferred' RETURN count(n)"),
                ("playbook", "MATCH (n:Memory:Playbook) RETURN count(n)"),
            ]:
                n = g.query(q).result_set[0][0]
                print(f"  {label:<10} {n}")
                ok &= n > 0
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["write", "verify"])
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    sys.exit(write() if a.action == "write" else verify(a.full))
