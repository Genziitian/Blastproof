"""The plan's G2 acceptance test, against the real stack, in two parts.

    TIMING_PROFILE=demo python -m scripts.acceptance part1
    docker compose down && docker compose up -d falkordb      # full restart, no reseed
    TIMING_PROFILE=demo python -m scripts.acceptance part2

part1: incident s01 (DB saturation on postgres-orders). The engineer confirms and
       asks for tickets with raw lines. The learner writes a sourced playbook.
       Needs a graph with no earlier incidents: if s01 can already be solved from
       memory, nothing new is learned. `--reset` wipes, re-creates the schema and
       reseeds the company graph first (make acceptance-1 passes it).
part2: after the restart, incident s04 (postgres-payments, new wording). The
       investigator runs as a separate process and is SIGKILLed after checkpoint 3;
       a second worker takes over. Then all seven acceptance checks are reported.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from agents.investigator import Investigator
from agents.learner import Learner
from agents.responder import Responder
from agents.triage import incident_key, open_incident
from common import config, db, logs
from common.db import graph
from eval import truth
from eval.oracle import Oracle
from scripts import seed, setup_schema
from scripts.run_incident import make_planner, run_incident
from sim.runtime import SimulatedWorld

STATE = Path(__file__).resolve().parent.parent / ".acceptance.json"
KILL_AFTER = 3


def q(g: Any, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
    return g.query(cypher, params or {}).result_set


def fresh_graph(company: str) -> bool:
    """Delete the company graph, then recreate its schema and seed it."""
    with contextlib.suppress(Exception):  # nothing to delete on a brand-new database
        graph(company).delete()
    print(f"company_{company}: deleted; recreating schema and seed")
    if not setup_schema.setup(company):
        return False
    seed.seed_company(company)
    return True


def part1(company: str, reset: bool) -> int:
    if reset and not fresh_graph(company):
        print("FAIL: schema constraints did not become OPERATIONAL")
        return 1
    g = graph(company)
    earlier = q(g, "MATCH (i:Incident) RETURN count(i)")[0][0]
    if earlier:
        print(f"FAIL: company_{company} already has {earlier} incident(s), so s01 would be "
              "solved from memory and teach nothing new.\n"
              "Rerun on a clean graph:  make acceptance-1   (passes --reset)")
        return 1
    incident_id = f"s01-{uuid.uuid4().hex[:6]}"
    key = run_incident(g, truth.load("s01"), incident_id)
    playbooks = q(g, "MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) "
                     "RETURN p.id, p.signature", {"k": key})
    prefs = q(g, "MATCH (f:Memory:Fact)-[:LEARNED_FROM]->(:Message)-[:IN]->(:Session)"
                 "-[:CONCERNS]->(:Incident {key: $k}) RETURN f.predicate, f.object", {"k": key})
    STATE.write_text(json.dumps({"company": company, "s01": incident_id}))
    print(f"\nincident {incident_id}: playbooks {playbooks}, preferences {prefs}")
    if not playbooks or not prefs:
        print("FAIL: part1 did not produce a playbook and preferences")
        return 1
    print("\npart1 done. Now restart the stack without reseeding:\n"
          "  docker compose down && docker compose up -d falkordb\n"
          "then run:  TIMING_PROFILE=demo python -m scripts.acceptance part2")
    return 0


def part2() -> int:
    if not db.wait_ready():
        print("FAIL: FalkorDB did not become ready after the restart")
        return 1
    state = json.loads(STATE.read_text())
    company, s01_id = state["company"], state["s01"]
    g = graph(company)
    t = truth.load("s04")
    incident_id = f"s04-{uuid.uuid4().hex[:6]}"
    key = incident_key(incident_id)
    task_id = f"{key}:investigate"

    world, oracle = SimulatedWorld(), Oracle()
    open_incident(g, incident_id, world.start(key, t.scenario()), world.observed_at(key))
    oracle.watch(key, t)

    worker = subprocess.Popen([sys.executable, "-m", "scripts.run_worker", "--company", company,
                               "--scenario", "s04", "--incident-id", incident_id,
                               "--instance", "worker-1", "--pace", "1.5"])
    while worker.poll() is None:
        done = q(g, "MATCH (:Task {id: $t})-[:HAS_CHECKPOINT]->(c) RETURN count(c)",
                 {"t": task_id})[0][0]
        if done >= KILL_AFTER:
            worker.kill()
            worker.wait()
            print(f"\nkilled worker-1 (SIGKILL) after checkpoint {done}")
            break
        time.sleep(0.2)

    deadline = time.time() + config.LEASE_TTL_MS / 1000 + 30
    replacement = Investigator(g, "worker-2", world, make_planner())
    while not replacement.run_once():
        if time.time() > deadline:
            print("FAIL: the task never became claimable again")
            return 1
        time.sleep(1)
    Responder(g, "responder-1", oracle, world).run_once()
    Learner(g, "learner-1").run_once()
    return report(g, s01_id, incident_id)


def report(g: Any, s01_id: str, s04_id: str) -> int:
    s01, s04 = incident_key(s01_id), incident_key(s04_id)
    task = f"{s04}:investigate"
    playbook = q(g, "MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) "
                    "RETURN p.id", {"k": s01})
    used = q(g, "MATCH (:Incident {key: $k})<-[:FOR]-(:Decision)-[u:USED]->(m:Memory:Playbook) "
                "WHERE u.applied RETURN m.id, u.target", {"k": s04})
    wording = q(g, "MATCH (a:Alert)-[:PART_OF]->(i:Incident) WHERE i.key IN [$a, $b] "
                   "RETURN i.key, collect(DISTINCT a.text)", {"a": s01, "b": s04})
    epochs = q(g, "MATCH (:Task {id: $t})-[:HAS_CHECKPOINT]->(c) RETURN c.n, c.epoch "
                  "ORDER BY c.n", {"t": task})
    task_state = q(g, "MATCH (t:Task {id: $t}) RETURN t.status, t.epoch", {"t": task})
    actions = q(g, "MATCH (:Incident {key: $k})<-[:FOR]-(:Task)-[:EMITTED]->(a:Action) "
                   "RETURN a.channel, a.payload", {"k": s04})

    texts = {row[0]: set(row[1]) for row in wording}
    ns = [n for n, _ in epochs]
    payload = actions[0][1] if len(actions) == 1 else ""
    checks = [
        ("1 playbook learned from s01, with its source", bool(playbook)),
        ("2 restart happened without reseeding (s01 memory still present)", bool(playbook)),
        ("3 related incident in new wording recalled it",
         bool(used) and texts.get(s01, set()).isdisjoint(texts.get(s04, set()))),
        ("4 worker-1 killed mid-investigation",
         any(e == 1 for _, e in epochs) and any(e > 1 for _, e in epochs)),
        ("5 replacement finished from the next checkpoint",
         bool(task_state) and task_state[0][0] == "done" and ns == list(range(1, len(ns) + 1))),
        ("6 preference applied and cited",
         len(actions) == 1 and actions[0][0] == "ticket" and s01_id in payload),
        ("7 exactly one notification", len(actions) == 1),
    ]
    print()
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\ncheckpoints (n, epoch): {epochs}")
    print(f"playbook used: {used}")
    return 0 if all(ok for _, ok in checks) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("part", choices=["part1", "part2"])
    ap.add_argument("--company", default="a", choices=config.COMPANIES)
    ap.add_argument("--reset", action="store_true",
                    help="part1 only: delete, re-schema and reseed the company graph first")
    args = ap.parse_args()
    logs.setup()
    if config.TIMING_PROFILE != "demo":
        print("note: TIMING_PROFILE is not 'demo'; the takeover waits for a 30 s lease")
    return part1(args.company, args.reset) if args.part == "part1" else part2()


if __name__ == "__main__":
    sys.exit(main())
