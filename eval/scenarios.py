"""The 30-incident benchmark and the M5 misleading-memory case.

Evaluator-only. `python -m eval.scenarios --write` turns the timeline below into
eval/truth/e01.json ... e30.json and m5a ... m5c.json; tests check the committed
files still match, so the answers can't drift from their definition.

The 30 incidents are replayed in time order into one graph per arm, so memory
builds up the way it would in a real company. Categories (plan, Evaluation):

  cold      6  first incidents, before any applicable memory exists
  repeat    6  same root and failure as an earlier incident, alert wording never seen before
  related   6  same failure on a sibling datastore of the same kind (reachable only by kind)
  same      6  symptoms match an existing playbook, evidence contradicts it
  novel     3  late incidents with plenty of memory nearby, none of it applicable
  org       3  on-call or ownership changed just before the incident

`cold` deviates from "2 per family": a second postgres or redis incident can always
recall the first one's playbook by kind, so only one per datastore family can be
truly cold; the other four cold starts are bad deploys on services with no history.

M5 runs separately: a wrong playbook (any postgres with more than 30% of its
connections in use "is saturated") is seeded, then three cache failures arrive. It
should mislead twice, retire, and the third incident should be diagnosed correctly.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chat.preferences import parse_rules
from memory.playbook import Check, Playbook
from sim import world as W

TRUTH_DIR = Path(__file__).resolve().parent / "truth"
HOUR = 3_600_000
START_MS = W.WORLD_START_MS + 2 * 24 * HOUR
SPACING_MS = 8 * HOUR
DEFAULT_CHANNEL = "page"

PRIYA_SAYS = ("For DB saturation, don't ping me on Slack. Open a ticket and paste the raw "
              "slow-query lines, not a summary.")
ROHAN_SAYS = "For bad deploys, page me and keep it to just a summary."


@dataclass(frozen=True)
class Spec:
    category: str
    family: str
    root: str
    says: str | None = None
    org: tuple[dict[str, str], ...] = ()


DB, DEPLOY, CACHE = "db_saturation", "bad_deploy", "cache_failure"

TIMELINE: tuple[Spec, ...] = (
    Spec("cold", DB, "postgres-orders", says=PRIYA_SAYS),
    Spec("cold", DEPLOY, "checkout-api", says=ROHAN_SAYS),
    Spec("cold", CACHE, "redis-cache"),
    Spec("cold", DEPLOY, "search-svc"),
    Spec("cold", DEPLOY, "payments-gw"),
    Spec("cold", DEPLOY, "cart-svc"),
    Spec("related", DB, "postgres-payments"),
    Spec("repeat", DB, "postgres-orders"),
    Spec("related", CACHE, "redis-sessions"),
    Spec("same", DEPLOY, "cart-svc"),
    Spec("repeat", DEPLOY, "checkout-api"),
    Spec("related", DB, "postgres-menu"),
    Spec("novel", DEPLOY, "menu-svc"),
    Spec("org", DB, "postgres-orders",
         org=({"kind": "on_call", "team": "platform-data", "person": "kabir"},)),
    Spec("same", DEPLOY, "payments-gw"),
    Spec("repeat", CACHE, "redis-cache"),
    Spec("related", DB, "postgres-payments"),
    Spec("same", DB, "postgres-orders"),
    Spec("org", CACHE, "redis-sessions",
         org=({"kind": "owner", "node": "redis-sessions", "team": "identity"},)),
    Spec("novel", DEPLOY, "auth-svc"),
    Spec("repeat", DEPLOY, "search-svc"),
    Spec("related", CACHE, "redis-sessions"),
    Spec("org", DB, "postgres-menu",
         org=({"kind": "on_call", "team": "platform-data", "person": "priya"},)),
    Spec("same", DEPLOY, "checkout-api"),
    Spec("repeat", DB, "postgres-orders"),
    Spec("related", DB, "postgres-menu"),
    Spec("novel", DEPLOY, "web-gateway"),
    Spec("same", DB, "postgres-payments"),
    Spec("repeat", CACHE, "redis-cache"),
    Spec("same", DEPLOY, "menu-svc"),
)

M5_TIMELINE: tuple[Spec, ...] = tuple(Spec("m5", CACHE, "redis-cache") for _ in range(3))
M5_PLAYBOOK_ID = "pb-seeded-wrong"
M5_PINNED_TO = "postgres-orders"
# Wrong on purpose: 30% of connections in use is normal (the baseline is about 42%),
# so this "confirms" saturation on a healthy database whenever it is recalled.
M5_PLAYBOOK = Playbook(
    signature="db_saturation:postgres", family=DB, applies_to_kind="postgres",
    params=("target",), preconditions=(),
    steps=(Check("inspect_metrics", {"node": "$target"}, "last:db_connections_pct", ">=", 30.0),),
)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Org:
    """Who owns what and who is on call, replayed alongside the timeline."""

    def __init__(self) -> None:
        self.owner = {node: team for team, (_, nodes) in W.TEAMS.items() for node in nodes}
        self.on_call: dict[str, str] = {}
        for handle, (_, team) in W.PEOPLE["a"].items():
            self.on_call.setdefault(team, handle)

    def apply(self, event: dict[str, str]) -> None:
        if event["kind"] == "on_call":
            self.on_call[event["team"]] = event["person"]
        else:
            self.owner[event["node"]] = event["team"]

    def recipient(self, root: str) -> tuple[str, str]:
        team = self.owner[root]
        return team, self.on_call[team]


def _wording(index: int, root: str, seen: dict[str, set[int]]) -> int:
    """Rotate through the eight phrasings; never reuse one already seen for this root."""
    w = index % 8
    while w in seen.setdefault(root, set()) and len(seen[root]) < 8:
        w = (w + 1) % 8
    seen[root].add(w)
    return w


def build(specs: tuple[Spec, ...], prefix: str, start_ms: int,
          number: bool = True) -> list[dict[str, Any]]:
    org = _Org()
    seen: dict[str, set[int]] = {}
    prefs: dict[tuple[str, str], str] = {}  # (handle, family) -> channel
    out = []
    for i, spec in enumerate(specs):
        onset = start_ms + i * SPACING_MS
        events = []
        for e in spec.org:
            org.apply(e)
            events.append({**e, "at": _iso(onset - HOUR)})
        team, recipient = org.recipient(spec.root)
        sid = f"{prefix}{i + 1:02d}" if number else f"{prefix}{chr(ord('a') + i)}"
        row: dict[str, Any] = {
            "id": sid, "category": spec.category, "family": spec.family, "root": spec.root,
            "onset": _iso(onset), "wording": _wording(i, spec.root, seen),
            "expected_owner_team": team, "expected_recipient": recipient,
            "expected_channel": prefs.get((recipient, spec.family), DEFAULT_CHANNEL),
        }
        if events:
            row["org_events"] = events
        if spec.says:
            row["engineer_says"] = spec.says
            for p in parse_rules(spec.says):
                if p.predicate == "preferred_channel" and p.condition_family:
                    prefs[(recipient, p.condition_family)] = p.value
        out.append(row)
    return out


def timeline() -> list[dict[str, Any]]:
    return build(TIMELINE, "e", START_MS)


def m5() -> list[dict[str, Any]]:
    return build(M5_TIMELINE, "m5", START_MS, number=False)


def ids() -> list[str]:
    return [r["id"] for r in timeline()]


def m5_ids() -> list[str]:
    return [r["id"] for r in m5()]


def write() -> list[Path]:
    paths = []
    for row in timeline() + m5():
        path = TRUTH_DIR / f"{row['id']}.json"
        path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write eval/truth/*.json")
    args = ap.parse_args()
    rows = timeline() + m5()
    if args.write:
        print(f"wrote {len(write())} truth files to {TRUTH_DIR}")
    for r in rows:
        print(f"{r['id']:<5} {r['category']:<8} {r['family']:<14} {r['root']:<18} "
              f"-> {r['expected_recipient']:<6} {r['expected_channel']:<7} w{r['wording']}")


if __name__ == "__main__":
    main()
