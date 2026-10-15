"""Deterministic incident simulator: three failure families, observable evidence only.

Agents see what the four evidence tools return, never the scenario's answer.
DB saturation and bad deploy deliberately produce the SAME user-facing symptoms
(checkout timeouts); only metrics, logs and recent changes tell them apart.

    from sim.families import Scenario, Evidence
    sc = Scenario("s01", "db_saturation", root="postgres-orders", onset_ms=...)
    ev = Evidence(sc)          # hand ONLY `ev` to the tool layer
    ev.inspect_metrics("postgres-orders")
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from sim import world as W

FAMILIES = ("db_saturation", "bad_deploy", "cache_failure")
MIN = 60_000


@dataclass(frozen=True)
class Scenario:
    id: str
    family: str
    root: str                 # failing node name (a datastore, or a service for bad_deploy)
    onset_ms: int             # scenario time the failure starts
    seed: int = 7
    wording: int = 0          # template variant, so repeats can use unseen phrasing
    alerting: tuple[str, ...] = field(default=())

    def __post_init__(self):
        if self.family not in FAMILIES:
            raise ValueError(f"unknown family {self.family}")
        if not self.alerting:
            object.__setattr__(self, "alerting", default_alerting(self.root))

    @property
    def now_ms(self) -> int:
        """Scenario time at which the investigation runs: 15 min after onset."""
        return self.onset_ms + 15 * MIN


def callers_of(node: str) -> set[str]:
    """Every node that depends on `node`, directly or transitively."""
    rev: dict[str, list[str]] = {}
    for a, b in W.DEPENDS_ON:
        rev.setdefault(b, []).append(a)
    seen, stack = set(), [node]
    while stack:
        for up in rev.get(stack.pop(), []):
            if up not in seen:
                seen.add(up)
                stack.append(up)
    return seen


def default_alerting(root: str) -> tuple[str, ...]:
    hit = callers_of(root) | ({root} if root in W.SERVICES else set())
    return tuple(sorted(s for s in hit if W.SERVICES.get(s, ("", False))[1]))


LOGS = {
    "db_saturation": {
        "root": ["FATAL: remaining connection slots are reserved for non-replication superuser connections",
                 "LOG: duration: {ms} ms  statement: SELECT * FROM {table} WHERE customer_id = $1",
                 "too many clients already (max_connections={max})"],
        "caller": ["timeout acquiring connection from pool after {ms}ms",
                   "upstream {dep} request exceeded deadline ({ms} ms)",
                   "pool exhausted: waited {ms}ms for a free connection"],
    },
    "bad_deploy": {
        "root": ["panic: nil pointer dereference in handler.ApplyPromo (build {build})",
                 "Traceback: KeyError 'promo_code' in pricing.apply (release {build})",
                 "500 Internal Server Error after release {build}"],
        "caller": ["upstream {dep} returned 500 ({ms} ms)",
                   "call to {dep} failed: internal error",
                   "{dep} responded with server error, retrying"],
    },
    "cache_failure": {
        "root": ["MISCONF Redis is configured to save RDB snapshots, but it is currently not able to persist",
                 "evicted {n} keys in the last minute (maxmemory reached)",
                 "connection refused from {host}"],
        "caller": ["cache miss storm: hit rate {pct}%",
                   "falling back to database for {dep} lookups",
                   "slow response: cache unavailable, {ms} ms"],
    },
}
NOISE = ["GET /healthz 200 2ms", "rotated access log", "config reloaded (no changes)",
         "GC pause 11ms", "worker heartbeat ok"]


class Evidence:
    """The ONLY object the tool layer receives. Returns observations, never the answer."""

    def __init__(self, scenario: Scenario):
        self._s = scenario
        self._affected = callers_of(scenario.root)

    def _rng(self, *parts) -> random.Random:
        return random.Random("|".join(map(str, (self._s.id, self._s.seed, *parts))))

    def _role(self, node: str) -> str:
        if node == self._s.root:
            return "root"
        return "caller" if node in self._affected else "healthy"

    def alerts(self) -> list[dict]:
        # Eight phrasings, so a repeat incident can arrive in wording never seen before.
        verbs = ["p95 latency above SLO", "slow responses breaching SLO", "latency alarm",
                 "response times degraded", "requests timing out for users",
                 "SLO burn rate high on latency", "user-facing slowness detected",
                 "tail latency spiking"]
        return [{"service": s, "signal": "latency",
                 "text": f"{s}: {verbs[self._s.wording % len(verbs)]}",
                 "fired_at": self._s.onset_ms + 3 * MIN}
                for s in self._s.alerting]

    def inspect_metrics(self, node: str, window_min: int = 30) -> dict:
        r, role, fam = self._rng("m", node), self._role(node), self._s.family
        times = [self._s.now_ms - (window_min - 5 * i) * MIN for i in range(window_min // 5 + 1)]
        after = [t >= self._s.onset_ms for t in times]

        def series(base, bad, jitter):
            return [round((bad if a else base) + r.uniform(-jitter, jitter), 1) for a in after]

        out: dict = {"node": node, "times_ms": times}
        if node in W.DATASTORES:
            kind = W.DATASTORES[node]
            if kind == "postgres":
                if fam == "db_saturation" and role == "root":
                    out["db_connections_pct"] = series(42, 98, 1.5)
                elif fam == "cache_failure" and role == "caller":
                    out["db_connections_pct"] = series(42, 74, 3)   # load rises, not saturated
                else:
                    out["db_connections_pct"] = series(42, 42, 4)
            elif kind == "redis":
                out["cache_hit_rate_pct"] = series(94, 8 if (fam == "cache_failure" and role == "root") else 94, 2)
            else:
                out["consumer_lag"] = series(120, 120, 30)
            return out
        degraded = role in ("root", "caller")
        out["latency_p95_ms"] = series(180, 2400 if degraded else 180, 40)
        err_bad = 35 if (fam == "bad_deploy" and role == "root") else (9 if degraded else 0.3)
        out["error_rate_pct"] = series(0.3, err_bad, 0.2)
        return out

    def inspect_logs(self, node: str, n: int = 6) -> list[str]:
        r, role = self._rng("l", node), self._role(node)
        lines = list(r.sample(NOISE, k=min(3, len(NOISE))))
        if role != "healthy":
            tpl = LOGS[self._s.family][role]
            for i in range(n - len(lines)):
                lines.append(tpl[(self._s.wording + i) % len(tpl)].format(
                    ms=r.randint(800, 5000), max=200, dep=self._s.root, build="r" + str(r.randint(4000, 4999)),
                    n=r.randint(2000, 9000), host=f"10.0.{r.randint(1, 9)}.{r.randint(2, 250)}",
                    pct=r.randint(3, 15), table=self._s.root.split('-')[-1]))
        r.shuffle(lines)
        return lines[:n]

    def inspect_recent_changes(self, service: str, hours: int = 2) -> list[dict]:
        changes: list[dict[str, Any]] = []
        if self._s.family == "bad_deploy" and service == self._s.root:
            changes.append({"service": service, "kind": "deploy",
                            "at_ms": self._s.onset_ms - 12 * MIN,
                            "summary": "release with pricing changes", "author": "rohan"})
        # Noise: an old, harmless change outside a 2-hour window.
        if service == "notify-svc":
            changes.append({"service": service, "kind": "config",
                            "at_ms": self._s.now_ms - 6 * 60 * MIN,
                            "summary": "template copy update", "author": "arjun"})
        cutoff = self._s.now_ms - hours * 60 * MIN
        return [c for c in changes if c["at_ms"] >= cutoff]

    def check_dependency_health(self, service: str) -> list[dict]:
        deps = [b for a, b in W.DEPENDS_ON if a == service]
        status = {"root": "unhealthy", "caller": "degraded", "healthy": "healthy"}
        return [{"dep": d, "status": status[self._role(d)],
                 "healthy": self._role(d) == "healthy"} for d in deps]
