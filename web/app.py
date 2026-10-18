"""The Blast Radius UI: one page, a small JSON API, everything read from FalkorDB.

    TIMING_PROFILE=demo python -m web.app --company a          # http://localhost:8000
    make ui                                                    # the same

It starts two investigator processes (killable), plus the responder and learner
in this process, and serves the Memory Lens, agent timeline, war room and map.
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from common import config, llm, logs
from common.db import graph, run, unavailable
from sim.store import ScenarioStore
from web.demo import Demo
from web.engineer import Engineer
from web.supervisor import Supervisor

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
BLOG = ROOT / "docs" / "blog"
log = logging.getLogger("web")
ASSET = re.compile(r"[a-z0-9-]+\.(js|css|json)")
FONT = re.compile(r"[a-z-]+-\d00\.woff2")
BLOG_FILE = re.compile(r"(assets|media|assets/fonts|assets/i18n)/[a-z0-9_-]+\.(js|css|json|jpg|png|mp4|webm|woff2)")
CYPHER_PATH = re.compile(r"(web|memory|coord|chat|tools|agents|sim)/queries/\w+\.cypher")


# What the engineer types goes to the graph verbatim and to the preference parser:
# bounded, so nobody can store or send a novel.
TEXT_MAX = 2000


class Break(BaseModel):
    node: str | None = Field(default=None, max_length=64)
    story: str | None = Field(default=None, max_length=16)


class Review(BaseModel):
    confirmed: bool
    message: str | None = Field(default=None, max_length=TEXT_MAX)


class Reply(BaseModel):
    text: str = Field(max_length=TEXT_MAX)


class Toggle(BaseModel):
    on: bool


class Arm(BaseModel):
    after: int | None = None


class HandOver(BaseModel):
    team: str
    person: str


class MoveOwner(BaseModel):
    node: str
    team: str


def latest_results(root: Path = ROOT) -> dict[str, Any]:
    from web.results import latest_results as read_results
    return read_results(root)


def create_app(demo: Demo, supervisor: Supervisor | None = None) -> FastAPI:
    app = FastAPI(title="Blast Radius", docs_url=None, redoc_url=None)

    def bad(e: Exception) -> HTTPException:
        return HTTPException(status_code=400, detail=str(e))

    def page(name: str) -> FileResponse:
        return FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})

    @app.get("/")
    def index() -> FileResponse:
        """The landing page: the idea, told with live data from the graph."""
        return page("landing.html")

    @app.get("/mission-control")
    def mission_control() -> FileResponse:
        """Mission control, the live demo: break a service and watch the agents work."""
        return page("mission.html")

    @app.get("/war-room")
    def war_room() -> RedirectResponse:
        """The page's earlier name."""
        return RedirectResponse("/mission-control")

    @app.get("/dark")
    def dark() -> FileResponse:
        """The previous dark war room, same API."""
        return page("dark.html")

    @app.get("/classic")
    def classic() -> FileResponse:
        """The first UI: every panel at once. Same API, kept as a fallback."""
        return page("classic.html")

    @app.get("/blog")
    def blog_slash() -> RedirectResponse:
        return RedirectResponse("/blog/")

    @app.get("/blog/")
    def blog() -> FileResponse:
        """The write-up: what we built, how it works, what we learned (also on GitHub Pages)."""
        return FileResponse(BLOG / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/blog/{rel:path}")
    def blog_file(rel: str) -> FileResponse:
        path = BLOG / rel
        if not BLOG_FILE.fullmatch(rel) or not path.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(path)

    @app.get("/static/{name}")
    def asset(name: str) -> FileResponse:
        path = STATIC / name
        if not ASSET.fullmatch(name) or not path.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.get("/fonts/{name}")
    def font(name: str) -> FileResponse:
        path = STATIC / "fonts" / name
        if not FONT.fullmatch(name) or not path.is_file():
            raise HTTPException(status_code=404, detail="no such font")
        return FileResponse(path, media_type="font/woff2",
                            headers={"Cache-Control": "max-age=86400"})

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
            "kill_after": demo.kill_after,
            "last_kill": demo.last_kill,
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

    @app.get("/api/db")
    def db_info() -> dict[str, Any]:
        return demo.db_info()

    @app.get("/api/cypher")
    def cypher(path: str) -> dict[str, str]:
        """The source of a query file, so each panel can show the Cypher behind it."""
        if not CYPHER_PATH.fullmatch(path) or not (ROOT / path).is_file():
            raise HTTPException(status_code=404, detail="no such query file")
        return {"path": path, "text": (ROOT / path).read_text(encoding="utf-8")}

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
        return {"ok": demo.engineer.submit(key, body.model_dump(), kind="review")}

    @app.post("/api/reply/{key}")
    def reply(key: str, body: Reply) -> dict[str, bool]:
        return {"ok": demo.engineer.submit(key, body.model_dump(), kind="readback")}

    @app.post("/api/autopilot")
    def autopilot(body: Toggle) -> dict[str, bool]:
        demo.engineer.autopilot = body.on
        return {"on": body.on}

    @app.post("/api/arm-kill")
    def arm_kill(body: Arm) -> dict[str, int | None]:
        demo.arm_kill(body.after)
        return {"after": demo.kill_after}

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

    @app.middleware("http")
    async def guard_writes(request: Any, call_next: Any) -> Any:
        """Every POST changes state. A public deployment refuses them all; locally,
        a POST sent by another site's page (CSRF, DNS rebinding) is refused too.
        Same-page requests and curl (no Origin header) still work."""
        if request.method == "POST":
            if config.PUBLIC_MODE:
                return JSONResponse(status_code=403, content={
                    "detail": "This public demo is read-only; run it locally for the controls."})
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse(status_code=403, content={"detail": "cross-site request refused"})
        return await call_next(request)

    @app.middleware("http")
    async def db_outage(request: Any, call_next: Any) -> Any:
        try:
            return await call_next(request)
        except Exception as exc:  # FalkorDB restarting: a calm 503 the page shows as a banner
            if not unavailable(exc):
                raise
            return JSONResponse(status_code=503, content={
                "detail": "FalkorDB is unavailable (restarting?); waiting for it", "db_down": True})

    @app.exception_handler(Exception)
    def failed(_: Any, exc: Exception) -> JSONResponse:
        log.exception("request failed")  # the details stay in the server log
        detail = f"{type(exc).__name__}: {exc}" if not config.PUBLIC_MODE else "internal error"
        return JSONResponse(status_code=500, content={"detail": detail})

    if "*" not in config.ALLOWED_HOSTS:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
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
    from common.db import wait_ready
    if not wait_ready():
        print("FalkorDB is not reachable: start it with `make db` (docker compose up -d falkordb)")
        return 1
    g = graph(args.company)
    if config.PUBLIC_MODE:
        # A public deployment starts every run from the seeded company, so a restart
        # never shows half-finished incidents from before it.
        with contextlib.suppress(Exception):
            g.delete()
        setup_schema.setup(args.company)
        seed.seed_company(args.company)
    elif not run(g, "web/queries/service_map.cypher", {}):
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

    engineer = Engineer(autopilot=args.autopilot or config.PUBLIC_MODE, handle_for=handle_for)
    def db_version() -> str:
        from common.db import client
        mods = client().connection.execute_command("MODULE", "LIST")
        for m in mods:
            info = dict(zip(m[::2], m[1::2], strict=False))
            name = info.get(b"name", info.get("name"))
            if name in (b"graph", "graph"):
                v = int(info.get(b"ver") or info.get("ver") or 0)
                return f"{v // 10000}.{v // 100 % 100}.{v % 100}"
        return "?"

    # In public mode the model is off unless PUBLIC_LLM=1: visitors can't run up a bill.
    model = None if config.PUBLIC_MODE and not os.getenv("PUBLIC_LLM") else llm.from_config()
    problem = llm.check(model)
    if problem:
        print(f"WARNING: {config.LLM_MODEL} did not answer a test request ({problem[:160]}).\n"
              "The agents will use the rule-based planner; the header says so.")
    demo = Demo(g, args.company, store, engineer, model, supervisor, reset_graph, db_version)
    if model is None:
        demo.model_status = "not configured"
    elif problem:
        demo.model_status = "unavailable: " + problem[:200]
    else:
        demo.model_status = "ok"
    demo.start_agents()
    if not args.no_workers:
        supervisor.start_all()
    if config.TIMING_PROFILE != "demo":
        print("note: TIMING_PROFILE is not 'demo'; a takeover waits for a 30 s lease")
    stop_public = threading.Event()
    if config.PUBLIC_MODE:
        print("PUBLIC_MODE: read-only; the story plays itself (s01 -> s04 with a kill -> s05)")
        threading.Thread(target=demo.public_loop, name="public-loop", daemon=True,
                         args=(stop_public, 8.0, config.PUBLIC_RESET_EVERY)).start()
    print(f"Blast Radius UI on http://{args.host}:{args.port}  ({config.graph_name(args.company)})")
    try:
        uvicorn.run(create_app(demo, supervisor), host=args.host, port=args.port,
                    log_level="warning")
    finally:
        stop_public.set()
        supervisor.stop_all()
        demo.stop_agents()
    return 0


if __name__ == "__main__":
    sys.exit(main())
