"""Run one investigator as its own process, so it can be killed for real.

    # one incident, simulator in this process (the acceptance test)
    python -m scripts.run_worker --company a --scenario s04 --incident-id s04-x --pace 1.5

    # a long-running worker that reads evidence from the shared simulator (the UI)
    python -m scripts.run_worker --company a --world .sim/company_a --forever --instance inv-1

With --scenario the process plays the simulator for that one incident itself. With
--world it reads each incident's evidence from the shared scenario store, so any
number of worker processes can investigate any incident, and take over each other's.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from typing import Any

from agents.investigator import Investigator
from agents.triage import incident_key
from common import config, logs
from common.db import graph
from scripts.run_incident import make_planner
from sim.runtime import SimulatedWorld
from sim.store import ScenarioStore


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--company", required=True, choices=config.COMPANIES)
    ap.add_argument("--scenario", help="play this scenario's simulator in-process")
    ap.add_argument("--incident-id", help="with --scenario: the incident to investigate")
    ap.add_argument("--world", help="shared scenario store directory (instead of --scenario)")
    ap.add_argument("--forever", action="store_true", help="keep claiming tasks until stopped")
    ap.add_argument("--instance", default="worker-1")
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to pause after each step")
    ap.add_argument("--exit-with-parent", action="store_true",
                    help="stop when the process that started this one goes away (the UI)")
    args = ap.parse_args()

    logs.setup()
    world: Any
    if args.world:
        world = ScenarioStore(args.world)
    elif args.scenario and args.incident_id:
        from eval import truth  # evaluator-only; this harness plays the simulator
        world = SimulatedWorld()
        world.start(incident_key(args.incident_id), truth.load(args.scenario).scenario())
    else:
        ap.error("give --world, or --scenario with --incident-id")
    worker = Investigator(graph(args.company), args.instance, world, make_planner(),
                          pace_s=args.pace)
    if not args.forever:
        return 0 if worker.run_once() else 1
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    if args.exit_with_parent:
        parent = os.getppid()

        def watch() -> None:
            while not stop.wait(1.0):
                if os.getppid() != parent:  # re-parented: the UI died without stopping us
                    stop.set()
        threading.Thread(target=watch, daemon=True).start()
    try:
        while not stop.is_set():
            try:
                if not worker.run_once():
                    stop.wait(0.5)
            except Exception:  # a bad task must not take the worker down; it is retried
                worker.log.exception("task failed; the lease will expire and it is retried")
                stop.wait(1.0)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
