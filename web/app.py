"""The Blast Radius UI: one page, a small JSON API, everything read from FalkorDB.

    TIMING_PROFILE=demo python -m web.app --company a          # http://localhost:8000
    make ui                                                    # the same

It starts two investigator processes (killable), plus the responder and learner
in this process, and serves the Memory Lens, agent timeline, war room and map.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from common import config, llm, logs
from common.db import graph, run
from sim.store import ScenarioStore
from web.demo import Demo
from web.engineer import Engineer
from web.supervisor import Supervisor

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
log = logging.getLogger("web")


class Break(BaseModel):
    node: str | None = None
    story: str | None = None


class Review(BaseModel):
    confirmed: bool
    message: str | None = None


class Reply(BaseModel):
    text: str


class Toggle(BaseModel):
    on: bool


class HandOver(BaseModel):
    team: str
    person: str


class MoveOwner(BaseModel):
    node: str
    team: str


def latest_results(root: Path = ROOT) -> dict[str, Any]:
    """The newest model-run eval summary and the load benchmark, if present."""
    out: dict[str, Any] = {"eval": None, "load": None}
    runs = sorted((root / "eval" / "results").glob("*/summary.json"))
    model_runs = [p for p in runs if not p.parent.name.endswith("rule-based")]
    for path in reversed(model_runs or runs):
        with contextlib.suppress(ValueError, OSError):
            data = json.loads(path.read_text(encoding="utf-8"))
            if len(data.get("meta", {}).get("arms", [])) >= 2:
                out["eval"] = {"name": path.parent.name, **data}
                break
    load = root / "bench" / "results" / "load.json"
    if load.exists():
        with contextlib.suppress(ValueError, OSError):
            out["load"] = json.loads(load.read_text(encoding="utf-8"))
    return out


def create_app(demo: Demo, supervisor: Supervisor | None = None) -> FastAPI:
    app = FastAPI(title="Blast Radius", docs_url=None, redoc_url=None)

    def bad(e: Exception) -> HTTPException:
        return HTTPException(status_code=400, detail=str(e))

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        return demo.settings()

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return {
            "incidents": demo.incidents(),
            "workers": supervisor.view() if supervisor else [],
            "threads": demo.thread_state,
            "pending": demo.engineer.pending(),
            "autopilot": demo.engineer.autopilot,
            "scenario_now": demo.now(),
        }

    @app.get("/api/incident/{key}")
    def incident(key: str) -> dict[str, Any]:
        found = demo.incident(key)
        if found is None:
            raise HTTPException(status_code=404, detail="no such incident")
        return found

    @app.get("/api/memory")
    def memory() -> dict[str, Any]:
        return demo.memory()

    @app.get("/api/map")
    def service_map() -> dict[str, Any]:
        return {"nodes": demo.service_map(), "org": demo.org_chart()}

    @app.get("/api/results")
    def results() -> dict[str, Any]:
        return latest_results()

    @app.get("/api/recap/{incident_id}")
    def recap(incident_id: str) -> dict[str, str]:
        return {"text": demo.recap(incident_id)}

    @app.post("/api/break")
    def break_(body: Break) -> dict[str, str]:
        try:
            key = demo.run_story(body.story) if body.story else demo.break_node(body.node or "")
        except ValueError as e:
            raise bad(e) from e
        return {"key": key}

    @app.post("/api/review/{key}")
    def review(key: str, body: Review) -> dict[str, bool]:
        return {"ok": demo.engineer.submit(key, body.model_dump())}

    @app.post("/api/reply/{key}")
    def reply(key: str, body: Reply) -> dict[str, bool]:
        return {"ok": demo.engineer.submit(key, body.model_dump())}

    @app.post("/api/autopilot")
    def autopilot(body: Toggle) -> dict[str, bool]:
        demo.engineer.autopilot = body.on
        return {"on": body.on}

    @app.post("/api/workers/{name}/kill")
    def kill(name: str) -> dict[str, Any]:
        if not supervisor or name not in supervisor.procs:
            raise HTTPException(status_code=404, detail="no such worker")
        return supervisor.kill(name)

    @app.post("/api/workers/{name}/start")
    def start(name: str) -> dict[str, Any]:
        if not supervisor or name not in supervisor.procs:
            raise HTTPException(status_code=404, detail="no such worker")
        return supervisor.start(name)

    @app.post("/api/org/on-call")
    def hand_over(body: HandOver) -> dict[str, bool]:
        try:
            demo.hand_over(body.team, body.person)
        except ValueError as e:
            raise bad(e) from e
        return {"ok": True}

    @app.post("/api/org/owner")
    def move_owner(body: MoveOwner) -> dict[str, bool]:
        try:
            demo.move_owner(body.node, body.team)
        except ValueError as e:
            raise bad(e) from e
        return {"ok": True}

    @app.post("/api/plant-wrong-memory")
    def plant() -> dict[str, str]:
        return {"id": demo.plant_wrong_memory()}

    @app.post("/api/reset")
    def reset() -> dict[str, bool]:
        demo.reset()
        return {"ok": True}

    @app.exception_handler(Exception)
    def failed(_: Any, exc: Exception) -> JSONResponse:
        log.exception("request failed")
        return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

    return app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--company", default="a", choices=config.COMPANIES)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--pace", type=float, default=1.5,
                    help="investigators pause this long after each step, so you can follow")
    ap.add_argument("--autopilot", action="store_true",
                    help="the scripted engineer answers instead of waiting for you")
    ap.add_argument("--no-workers", action="store_true", help="don't start investigators")
    args = ap.parse_args()

    import uvicorn

    from scripts import seed, setup_schema

    logs.setup()
    g = graph(args.company)
    if not run(g, "web/queries/service_map.cypher", {}):
        print(f"{config.graph_name(args.company)} is empty: run `make schema seed` first")
        return 1
    store = ScenarioStore(ROOT / ".sim" / config.graph_name(args.company))
    supervisor = Supervisor(args.company, store.root, pace_s=args.pace)

    def handle_for(key: str) -> str | None:
        rows = run(g, "coord/queries/read_action.cypher",
                   {"intent_key": f"{key}:initial-notification"})
        return rows[0]["recipient"] if rows else None

    def reset_graph() -> None:
        with contextlib.suppress(Exception):
            g.delete()
        setup_schema.setup(args.company)
        seed.seed_company(args.company)

    engineer = Engineer(autopilot=args.autopilot, handle_for=handle_for)
    demo = Demo(g, args.company, store, engineer, llm.from_config(), supervisor, reset_graph)
    demo.start_agents()
    if not args.no_workers:
        supervisor.start_all()
    if config.TIMING_PROFILE != "demo":
        print("note: TIMING_PROFILE is not 'demo'; a takeover waits for a 30 s lease")
    print(f"Blast Radius UI on http://{args.host}:{args.port}  ({config.graph_name(args.company)})")
    try:
        uvicorn.run(create_app(demo, supervisor), host=args.host, port=args.port,
                    log_level="warning")
    finally:
        supervisor.stop_all()
        demo.stop_agents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
