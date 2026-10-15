"""Run one worker as its own process, so it can be killed for real.

    python -m scripts.run_worker --company a --scenario s04 --incident-id s04-x --pace 1.5

The process plays the simulator for this one incident (so its evidence tools work)
and runs an investigator until the task is done or the process is killed.
"""
from __future__ import annotations

import argparse
import sys

from agents.investigator import Investigator
from agents.triage import incident_key
from common import config, logs
from common.db import graph
from eval import truth
from scripts.run_incident import make_planner
from sim.runtime import SimulatedWorld


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--company", required=True, choices=config.COMPANIES)
    ap.add_argument("--scenario", required=True, choices=truth.all_ids())
    ap.add_argument("--incident-id", required=True)
    ap.add_argument("--instance", default="worker-1")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to pause after each step")
    args = ap.parse_args()

    logs.setup()
    world = SimulatedWorld()
    world.start(incident_key(args.incident_id), truth.load(args.scenario).scenario())
    worker = Investigator(graph(args.company), args.instance, world, make_planner(),
                          pace_s=args.pace)
    return 0 if worker.run_once() else 1


if __name__ == "__main__":
    sys.exit(main())
