"""Prove data survives a restart without being reseeded.

    python -m scripts.persistence_check write     # before restarting
    docker compose down && docker compose up -d
    python -m scripts.persistence_check verify    # after

`write` stores a marker in each company graph, along with how many incidents,
checkpoints, preference facts and playbooks it holds. `verify` passes when every
marker is back and no company has fewer of those than before the restart.

With --full (Gate G2 on), at least one company must also have run an incident,
so the check covers data created after seeding, not just the marker. A company
that has run nothing yet (often company_b) is reported, not failed.
"""
from __future__ import annotations

import argparse
import sys
import uuid

from common import config
from common.db import graph

COUNTS = {
    "incidents": "MATCH (n:Incident) RETURN count(n)",
    "checkpoints": "MATCH (n:Checkpoint) RETURN count(n)",
    "preferences": "MATCH (n:Memory:Fact) WHERE n.predicate STARTS WITH 'preferred' RETURN count(n)",
    "playbooks": "MATCH (n:Memory:Playbook) RETURN count(n)",
}


def counts(g) -> dict[str, int]:
    return {name: g.query(q).result_set[0][0] for name, q in COUNTS.items()}


def write() -> int:
    for cid in config.COMPANIES:
        g, token = graph(cid), uuid.uuid4().hex[:8]
        now = counts(g)
        g.query("MERGE (m:PersistenceMarker {key: 'persist'}) "
                "SET m.token = $t, m.at = timestamp(), m.incidents = $incidents, "
                "m.checkpoints = $checkpoints, m.preferences = $preferences, "
                "m.playbooks = $playbooks", {"t": token, **now})
        print(f"company_{cid}: marker {token} written  {now}")
    return 0


def verify(full: bool) -> int:
    ok, any_complete = True, False
    for cid in config.COMPANIES:
        g = graph(cid)
        rows = g.query("MATCH (m:PersistenceMarker {key: 'persist'}) "
                       "RETURN m.token, m.incidents, m.checkpoints, m.preferences, "
                       "m.playbooks").result_set
        if not rows:
            print(f"company_{cid}: marker MISSING")
            ok = False
            continue
        token, *recorded = rows[0]
        before = dict(zip(COUNTS, (r or 0 for r in recorded), strict=True))
        after = counts(g)
        print(f"company_{cid}: marker found {token}")
        for name in COUNTS:
            kept = after[name] >= before[name]
            ok &= kept
            print(f"  {name:<12} {before[name]:>4} before  {after[name]:>4} after"
                  f"{'' if kept else '   LOST'}")
        if all(after.values()):
            any_complete = True
        elif full:
            print("  (no incident with a learned playbook and preference here yet; not required)")
    if full and not any_complete:
        print("FAIL --full: no company has an incident, checkpoint, preference and playbook. "
              "Run `make incident` (or acceptance part1) before `write`.")
        ok = False
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["write", "verify"])
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    sys.exit(write() if a.action == "write" else verify(a.full))
