"""Run scenarios end to end: alerts -> triage -> investigator -> responder -> learner.

    python -m scripts.run_incident --company a --scenario s01
    python -m scripts.run_incident --company a --scenario s01 s04 s05   # the demo story
    python -m scripts.run_incident --company a --scenario s04 --no-memory

All workers run in this process. The oracle stands in for the on-call engineer:
it confirms or rejects each diagnosis and says what the scenario scripts it to say.
With LLM_MODEL set, the investigator plans with the model (rule-based fallback).
"""
from __future__ import annotations

import argparse
import sys
import uuid
from typing import Any

from agents.contracts import Confirmer
from agents.investigator import Investigator
from agents.learner import Learner
from agents.llm_planner import GuardedLLMPlanner
from agents.planning import Planner, RuleBasedPlanner
from agents.responder import Responder
from agents.triage import incident_key, open_incident
from chat.war_room import WarRoom
from common import config, llm, logs
from common.db import graph, run
from eval import truth
from eval.oracle import Oracle
from sim.runtime import SimulatedWorld


def make_planner() -> Planner:
    model = llm.from_config()
    return GuardedLLMPlanner(model) if model else RuleBasedPlanner()


def run_incident(g: Any, t: truth.Truth, incident_id: str, *, use_memory: bool = True,
                 planner: Planner | None = None, instance: str = "local",
                 confirmer: Confirmer | None = None, learn: bool = True) -> str:
    """Triage, investigate, respond and (unless learn=False) learn, in this process.

    The oracle reviews the diagnosis unless another `confirmer` is given.
    """
    world, oracle = SimulatedWorld(), Oracle()
    key = incident_key(incident_id)
    alerts = world.start(key, t.scenario())
    oracle.watch(key, t)

    open_incident(g, incident_id, alerts, world.observed_at(key))
    Investigator(g, f"{instance}-investigator", world, planner,
                 use_memory=use_memory).run_once()
    Responder(g, f"{instance}-responder", confirmer or oracle, world,
              WarRoom(g, llm.from_config())).run_once()
    if learn:
        Learner(g, f"{instance}-learner").run_once()
    return key


def report(g: Any, key: str) -> list[str]:
    lines = [f"{'task':<52} {'type':<12} {'status':<8} {'ckpts':>5} {'actions':>7}"]
    for r in run(g, "agents/queries/incident_report.cypher", {"incident_key": key}):
        lines.append(f"{r['task']:<52} {r['type']:<12} {r['status']:<8} "
                     f"{r['checkpoints']:>5} {r['actions']:>7}")
    o = run(g, "agents/queries/incident_outcome.cypher", {"incident_key": key})[0]
    lines += [
        "",
        f"diagnosis  {o['root']} ({o['family']})",
        f"verdict    {o['verdict']}",
        f"notified   {', '.join(o['notified']) or 'nobody'}",
        f"incident   {o['status']}  signature={o['signature']}",
    ]
    for u in run(g, "agents/queries/incident_memory.cypher", {"incident_key": key}):
        lines.append(f"memory     {u['memory']} -> {u['target']}: "
                     f"{'applied' if u['applied'] else 'ruled out'}, verdict={u['verdict']}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--company", required=True, choices=config.COMPANIES)
    ap.add_argument("--scenario", required=True, nargs="+", choices=truth.all_ids())
    ap.add_argument("--no-memory", action="store_true", help="investigate without recall")
    args = ap.parse_args()

    logs.setup()
    g = graph(args.company)
    planner = make_planner()
    for sid in args.scenario:
        incident_id = f"{sid}-{uuid.uuid4().hex[:6]}"
        key = run_incident(g, truth.load(sid), incident_id,
                           use_memory=not args.no_memory, planner=planner)
        print(f"\n== {sid} ==")
        print("\n".join(report(g, key)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
