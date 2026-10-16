"""Load benchmark (M8): two companies, N worker pairs each, incidents fired at once.

    python -m bench.load                 # 1, 2 and 4 worker pairs, 20 incidents
    python -m bench.load --pairs 2 --incidents 20

Every worker (investigator, responder, learner) runs its own claim loop in a
thread, all against the same two company graphs, exactly as separate processes
would: they share nothing but FalkorDB. The deterministic planner is used, so
this measures the database and the coordination protocol, not a model.

A task that keeps losing its worker stops after 3 attempts and waits for a human
(`stuck_for_a_human`), rather than retrying forever.

Reported: p50/p95 latency of memory reads (recall, preferences, checkpoints read
back) and writes (checkpoints, decisions, actions, verdicts, playbooks, facts),
incidents per minute, duplicate notifications (must be 0), lost leases (a worker
stopped because another holds the task) and takeovers (tasks claimed more than once).

With --chaos-ms N, a chaos thread expires a random held lease every N ms, as if
that worker had stalled: another worker takes the task over, and the stalled
one's next fenced write is rejected. Duplicates must still be 0.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from statistics import quantiles
from typing import Any

from agents.investigator import Investigator
from agents.learner import Learner
from agents.planning import RuleBasedPlanner
from agents.responder import Responder
from agents.triage import incident_key, open_incident
from agents.worker import Worker
from chat.war_room import WarRoom
from common import db, logs
from common.db import raw_graph
from eval import scenarios, truth
from eval.oracle import Oracle
from scripts.seed import seed_graph
from sim import deploys
from sim.runtime import SimulatedWorld

RESULTS = Path(__file__).resolve().parent / "results"
READS = ("memory/queries/recall", "memory/queries/playbooks_by_id", "chat/queries/preferences_for",
         "coord/queries/read_checkpoints", "agents/queries/decision_usage",
         "agents/queries/learn_context", "agents/queries/respond_context")
WRITES = ("coord/queries/checkpoint", "coord/queries/send_action", "coord/queries/claim",
          "coord/queries/handoff", "coord/queries/complete", "coord/queries/heartbeat",
          "agents/queries/record_decision", "agents/queries/record_usage",
          "agents/queries/confirm", "memory/queries/feedback", "memory/queries/write_playbook",
          "memory/queries/add_provenance", "memory/queries/fact_supersede",
          "chat/queries/add_message")


def _pct(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50_ms": None, "p95_ms": None, "n": 0}
    if len(values) == 1:
        return {"p50_ms": round(values[0] * 1000, 2), "p95_ms": round(values[0] * 1000, 2), "n": 1}
    q = quantiles(values, n=100, method="inclusive")
    return {"p50_ms": round(q[49] * 1000, 2), "p95_ms": round(q[94] * 1000, 2), "n": len(values)}


def _loop(worker: Worker, stop: threading.Event, errors: list[str]) -> None:
    while not stop.is_set():
        try:
            if not worker.run_once():
                stop.wait(0.02)
        except Exception as e:  # keep the benchmark running; report what broke
            errors.append(f"{worker.instance}: {type(e).__name__}: {e}")
            stop.wait(0.05)


def _count(g: Any, cypher: str) -> int:
    return int(g.query(cypher).result_set[0][0])


CHAOS = ("MATCH (t:Task {status: 'leased'}) WITH t ORDER BY t.id LIMIT 1 "
         "SET t.lease_until = timestamp() - 1 RETURN t.id AS id")


def _chaos(graphs: list[Any], every_s: float, stop: threading.Event, hits: list[str]) -> None:
    i = 0
    while not stop.wait(every_s):
        g = graphs[i % len(graphs)]
        i += 1
        with contextlib.suppress(Exception):
            hits += [r[0] for r in g.query(CHAOS).result_set]


def run_load(make_graph: Callable[[str], Any], pairs: int, incidents: int,
             companies: tuple[str, ...] = ("a", "b"), timeout_s: float = 120.0,
             chaos_ms: int = 0) -> dict[str, Any]:
    ids = scenarios.ids()[: max(1, incidents // len(companies))]
    graphs = {c: make_graph(f"bench_{c}") for c in companies}
    for c, g in graphs.items():
        seed_graph(g, c)
    world, oracle = SimulatedWorld(), Oracle()
    stop, errors, threads = threading.Event(), [], []
    for c, g in graphs.items():
        for i in range(pairs):
            for w in (Investigator(g, f"{c}-inv-{i}", world, RuleBasedPlanner()),
                      Responder(g, f"{c}-resp-{i}", oracle, world, WarRoom(g, None)),
                      Learner(g, f"{c}-learn-{i}")):
                threads.append(threading.Thread(target=_loop, args=(w, stop, errors),
                                                daemon=True))
    expired: list[str] = []
    if chaos_ms:
        threads.append(threading.Thread(target=_chaos, daemon=True, args=(
            list(graphs.values()), chaos_ms / 1000, stop, expired)))
    timings = db.Timings()
    db.record_timings(timings)
    losses_before = Worker.lease_losses
    started = time.perf_counter()
    try:
        for g in graphs.values():  # every incident fires at once, then workers start
            for sid in ids:
                t = truth.load(sid)
                key = incident_key(sid)
                oracle.watch(key, t)
                alerts = world.start(key, t.scenario())
                deploys.publish(g, key, t.scenario())
                open_incident(g, sid, alerts, world.observed_at(key))
        for th in threads:
            th.start()
        expected = len(ids)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            done = [_count(g, "MATCH (t:Task {type: 'learn', status: 'done'}) RETURN count(t)")
                    for g in graphs.values()]
            if all(d >= expected for d in done):
                break
            time.sleep(0.05)
        elapsed = time.perf_counter() - started
    finally:
        stop.set()
        for th in threads:
            th.join(timeout=5)
        db.record_timings(None)

    reads = [s for q, s in timings.samples if q.startswith(READS)]
    writes = [s for q, s in timings.samples if q.startswith(WRITES)]
    total = 0
    duplicates = takeovers = stuck = 0
    for g in graphs.values():
        total += _count(g, "MATCH (t:Task {type: 'learn', status: 'done'}) RETURN count(t)")
        duplicates += _count(g, "MATCH (i:Incident)<-[:FOR]-(:Task)-[:EMITTED]->(a:Action) "
                                "WITH i, count(a) AS n WHERE n > 1 RETURN count(i)")
        takeovers += _count(g, "MATCH (t:Task) WHERE t.epoch > 1 RETURN count(t)")
        stuck += _count(g, "MATCH (t:Task) WHERE t.status <> 'done' AND t.attempts >= 3 "
                           "RETURN count(t)")
    return {
        "companies": list(companies), "worker_pairs_per_company": pairs,
        "incidents": len(ids) * len(companies), "completed": total,
        "seconds": round(elapsed, 3),
        "incidents_per_minute": round(total / elapsed * 60, 1) if elapsed else None,
        "memory_reads": _pct(reads), "memory_writes": _pct(writes),
        "duplicate_notifications": duplicates, "takeovers": takeovers,
        "lost_leases": Worker.lease_losses - losses_before, "errors": errors[:10],
        "chaos_ms": chaos_ms, "leases_expired_by_chaos": len(expired),
        "stuck_for_a_human": stuck,
    }


def live_graph(name: str) -> Any:
    g = raw_graph(name)
    with contextlib.suppress(Exception):
        g.delete()
    return raw_graph(name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pairs", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--incidents", type=int, default=20)
    ap.add_argument("--chaos-ms", type=int, default=0, help="expire a held lease this often")
    args = ap.parse_args()
    logs.setup("ERROR")
    results = [run_load(live_graph, p, args.incidents, chaos_ms=args.chaos_ms)
               for p in args.pairs]
    if not args.chaos_ms:  # the same load again with stalled workers
        results += [run_load(live_graph, max(args.pairs), args.incidents, chaos_ms=50)]
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "load.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("| worker pairs / company | chaos | incidents | per minute | read p50 / p95 ms | "
          "write p50 / p95 ms | duplicate notifications | takeovers | lost leases |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        rd, wr = r["memory_reads"], r["memory_writes"]
        chaos = f"every {r['chaos_ms']} ms" if r["chaos_ms"] else "none"
        print(f"| {r['worker_pairs_per_company']} | {chaos} | {r['completed']}/{r['incidents']} | "
              f"{r['incidents_per_minute']} | {rd['p50_ms']} / {rd['p95_ms']} | "
              f"{wr['p50_ms']} / {wr['p95_ms']} | {r['duplicate_notifications']} | "
              f"{r['takeovers']} | {r['lost_leases']} |")
        if r["errors"]:
            print("errors:", *r["errors"], sep="\n  ")
    print(f"\nwritten to {RESULTS / 'load.json'}")
    ok = all(r["duplicate_notifications"] == 0 and r["completed"] == r["incidents"]
             for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
