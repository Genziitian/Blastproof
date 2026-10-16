"""What the UI can do and see, independent of HTTP (so tests can drive it).

The UI plays two outside roles, never an agent's:
- the world: it breaks a service (writes the hidden scenario to the shared
  simulator, then raises the alerts through triage), or changes the org chart;
- the on-call engineer: confirms or rejects diagnoses and talks in the war room.

Agents run as they always do: investigators as separate processes (killable), the
responder and learner as threads here. Everything shown is read back from FalkorDB.
"""
from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from agents.learner import Learner
from agents.responder import Responder
from agents.triage import incident_key, open_incident
from agents.worker import Worker
from chat.war_room import WarRoom
from common import config
from common.db import Outage, run, unavailable
from coord import tasks
from sim import deploys, org
from sim import world as W
from sim.families import Scenario
from sim.store import ScenarioStore
from web.engineer import Cancelled, Engineer, Script

log = logging.getLogger("web")
ROOT = Path(__file__).resolve().parent.parent
Q = "web/queries/"
HOUR = 3_600_000
FIRST_ONSET = W.WORLD_START_MS + 2 * 24 * HOUR
SPACING = 8 * HOUR
FAMILY_OF_KIND = {"postgres": "db_saturation", "redis": "cache_failure"}
LABELS = {"db_saturation": "DB saturation", "bad_deploy": "bad deploy",
          "cache_failure": "cache failure"}

STORIES = {
    "s01": "Orders DB saturates (first time)",
    "s02": "Bad deploy on checkout-api",
    "s03": "Cache failure on redis-cache",
    "s04": "Payments DB saturates, new wording",
    "s05": "Checkout errors again, different cause",
}


def _json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


class Demo:
    def __init__(self, graph: Any, company: str, store: ScenarioStore, engineer: Engineer,
                 chat_model: Any = None, supervisor: Any = None, reset_graph: Any = None,
                 db_version: Any = None) -> None:
        self.graph = graph
        self.company = company
        self.store = store
        self.engineer = engineer
        self.chat_model = chat_model
        self.supervisor = supervisor
        self.reset_graph = reset_graph  # callable that wipes, re-schemas and reseeds
        self.db_version = db_version    # callable returning the FalkorDB module version
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self.thread_state: dict[str, str] = {}
        self.model_status: str | None = None     # set at startup from llm.check()
        self.kill_after: int | None = None       # armed kill: SIGKILL after this step
        self.last_kill: dict[str, Any] | None = None

    # ------------------------------------------------------------ agents here
    def start_agents(self) -> None:
        """The responder and learner, each in its own claim loop, in this process."""
        self._stop.clear()
        for w in self.agents():
            t = threading.Thread(target=self._loop, args=(w,), name=w.instance, daemon=True)
            self._threads.append(t)
            t.start()
        t = threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True)
        self._threads.append(t)
        t.start()

    def arm_kill(self, after: int | None) -> None:
        """One shot: SIGKILL whichever investigator holds a fresh lease once it has
        checkpointed `after` steps. The same real kill as the button, just on time."""
        self.kill_after = after if after and after > 0 else None

    def check_armed_kill(self) -> str | None:
        if not self.kill_after or self.supervisor is None:
            return None
        for r in run(self.graph, Q + "held_investigations.cypher", {}):
            proc = self.supervisor.procs.get(r["owner"])
            if r["epoch"] == 1 and r["steps"] >= self.kill_after and proc and proc.alive():
                self.supervisor.kill(r["owner"])
                self.last_kill = {"worker": r["owner"], "task": r["id"], "after_step": r["steps"]}
                self.kill_after = None
                log.info("armed kill: SIGKILL %s after step %s of %s",
                         r["owner"], r["steps"], r["id"])
                return str(r["owner"])
        return None

    def _housekeeping(self) -> None:
        """Armed kill (every 0.1 s) and the stuck sweep (every 2 s): a task whose lease ran
        out on its last allowed attempt is marked stuck, for a human to look at."""
        ticks = 0
        outage = Outage(log, "housekeeping")
        while not self._stop.wait(0.1):
            ticks += 1
            try:
                self.check_armed_kill()
                if ticks % 20 == 0:
                    for task_id in tasks.stuck_sweep(self.graph):
                        log.warning("%s is stuck after %s attempts; needs a human",
                                    task_id, config.MAX_ATTEMPTS)
                outage.ok()
            except Exception as e:
                if unavailable(e):
                    outage.failed()
                    self._stop.wait(1.0)
                else:
                    log.exception("housekeeping failed")

    def agents(self) -> list[Worker]:
        return [Responder(self.graph, "responder-1", self.engineer, self.store,
                          WarRoom(self.graph, self.chat_model)),
                Learner(self.graph, "learner-1")]

    def _loop(self, worker: Worker) -> None:
        outage = Outage(log, worker.instance)
        while not self._stop.is_set():
            try:
                self.thread_state[worker.instance] = "idle"
                busy = worker.run_once()
                outage.ok()
                if not busy:
                    self._stop.wait(0.3)
            except Cancelled:
                log.info("%s: reset while waiting for the engineer", worker.instance)
            except Exception as e:
                if unavailable(e):
                    outage.failed()
                else:
                    log.exception("%s failed; the task is retried after its lease",
                                  worker.instance)
                self._stop.wait(1.0)

    def stop_agents(self) -> None:
        self._stop.set()
        self.engineer.cancel_all()
        for t in self._threads:
            t.join(timeout=5)
        self._threads.clear()

    # ------------------------------------------------------------ scenario clock
    def _last_observed(self) -> int | None:
        rows = run(self.graph, Q + "last_observed.cypher", {})
        return rows[0]["last"] if rows else None

    def next_onset(self) -> int:
        last = self._last_observed()
        return FIRST_ONSET if last is None else last - 15 * 60_000 + SPACING

    def now(self) -> int:
        """Scenario time 'now', between the last incident and the next one."""
        last = self._last_observed()
        return FIRST_ONSET - HOUR if last is None else last + HOUR

    # ------------------------------------------------------------ the world
    def breakable(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {s: "bad_deploy" for s in W.SERVICES}
        out.update({d: FAMILY_OF_KIND.get(k) for d, k in W.DATASTORES.items()})
        return out

    def break_node(self, node: str, says: str | None = None) -> str:
        family = self.breakable().get(node)
        if not family:
            raise ValueError(f"{node} can't be broken in this simulator")
        count = run(self.graph, Q + "root_count.cypher", {"node": node})[0]["n"]
        return self._start(node, family, node, wording=(count * 3 + 1) % 8,
                           says=says)

    def run_story(self, sid: str) -> str:
        if sid not in STORIES:
            raise ValueError(f"unknown story {sid}")
        from eval import truth  # the UI plays the world; agents never see this
        t = truth.load(sid)
        return self._start(sid, t.family, t.root, wording=t.wording, says=t.engineer_says)

    def _start(self, label: str, family: str, root: str, wording: int,
               says: str | None) -> str:
        with self._lock:
            incident_id = f"{label}-{uuid.uuid4().hex[:4]}"
            key = incident_key(incident_id)
            scenario = Scenario(incident_id, family, root, self.next_onset(), wording=wording)
            alerts = self.store.start(key, scenario)
            deploys.publish(self.graph, key, scenario)
            self.engineer.watch(key, Script(root, family, says))
            open_incident(self.graph, incident_id, alerts, self.store.observed_at(key))
        log.info("broke %s (%s) as %s", root, family, key)
        return key

    def hand_over(self, team: str, person: str) -> None:
        if team not in W.TEAMS or person not in W.PEOPLE[self.company]:
            raise ValueError("unknown team or person")
        org.hand_over_on_call(self.graph, team, person, self.now())

    def move_owner(self, node: str, team: str) -> None:
        if node not in self.breakable() or team not in W.TEAMS:
            raise ValueError("unknown node or team")
        org.move_ownership(self.graph, node, team, self.now())

    def plant_wrong_memory(self) -> str:
        """M5: a playbook that is wrong on purpose. Watch evidence and verdicts retire it."""
        from eval import scenarios
        # Its own signature, so the learner never files a real lesson under it.
        wrong = replace(scenarios.M5_PLAYBOOK, signature="db_saturation:postgres:planted")
        at = self.now()
        planted = f"planted-{uuid.uuid4().hex[:4]}"
        pid = f"pb-wrong-{planted}"
        run(self.graph, "agents/queries/open_incident.cypher", {
            "incident_key": incident_key(planted), "incident_id": planted, "alerts": [],
            "observed_at": at})
        run(self.graph, "memory/queries/write_playbook.cypher", {
            **wrong.fields(), "id": pid,
            "incident_key": incident_key(planted), "root": scenarios.M5_PINNED_TO,
            "scenario_now": at})
        run(self.graph, Q + "mark_planted.cypher", {"incident_key": incident_key(planted)})
        return pid

    def reset(self) -> None:
        if self.reset_graph is None:
            raise RuntimeError("reset is not available here")
        if self.supervisor:
            self.supervisor.stop_all()
        self.stop_agents()
        self.store.clear()
        self.reset_graph()
        self.start_agents()
        if self.supervisor:
            self.supervisor.start_all()

    # ------------------------------------------------------------ reads
    def incidents(self, limit: int = 40) -> list[dict[str, Any]]:
        return run(self.graph, Q + "incidents.cypher", {"limit": limit})

    def incident(self, key: str) -> dict[str, Any] | None:
        stats = {"queries": 0, "ms": 0.0}

        def q(path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            started = time.perf_counter()
            rows = run(self.graph, path, params)
            stats["queries"] += 1
            stats["ms"] += (time.perf_counter() - started) * 1000
            return rows

        head = q(Q + "incident_head.cypher", {"incident_key": key})
        if not head:
            return None
        p = {"incident_key": key}
        lens = q(Q + "lens.cypher", p)
        for row in lens:
            checks = _json(row.pop("checks_json")) or {}
            row["checks"] = checks.get("checks", []) if isinstance(checks, dict) else []
            row["note"] = checks.get("note", "") if isinstance(checks, dict) else ""
        checkpoints = q(Q + "checkpoints.cypher", p)
        for c in checkpoints:
            c["args"] = _json(c.pop("args_json"))
            obs = _json(c.pop("observation"))
            c["result"] = obs.get("result") if isinstance(obs, dict) else obs
        actions = q(Q + "actions.cypher", p)
        for a in actions:
            a["payload"] = _json(a["payload"])
        tasks = q(Q + "tasks.cypher", p)
        recalling: list[dict[str, Any]] = []
        for t in tasks:
            recalling = recalling or (_json(t.pop("recalled_json")) or [])
            t.pop("recalled_json", None)
        root = head[0]["root"]
        impact = (q("tools/queries/blast_radius.cypher", {"node": root})
                  if root and root != "unknown" else [])
        messages = q(Q + "messages.cypher", p)
        handle = actions[0]["recipient"] if actions else None
        earlier = [m for m in (WarRoom(self.graph).recent(handle, 8) if handle else [])
                   if m["incident"] != head[0]["id"]][:6]
        return {
            "head": head[0], "lens": lens, "tasks": tasks, "checkpoints": checkpoints,
            "actions": actions, "messages": messages, "impact": impact,
            "recalling": recalling, "earlier": earlier, "timeline": timeline(tasks, checkpoints, actions, head[0]),
            "db": {"queries": stats["queries"], "ms": round(stats["ms"], 1)},
        }

    def memory(self) -> dict[str, Any]:
        playbooks = run(self.graph, Q + "playbooks.cypher", {})
        for pb in playbooks:
            pb["preconditions"] = _json(pb.pop("preconditions_json")) or []
            pb["steps"] = _json(pb.pop("steps_json")) or []
        return {"playbooks": playbooks, "facts": run(self.graph, Q + "facts.cypher", {})}

    def db_info(self) -> dict[str, Any]:
        size = run(self.graph, Q + "graph_size.cypher", {})
        version = None
        if self.db_version is not None:
            with contextlib.suppress(Exception):
                version = self.db_version()
        return {"graph": config.graph_name(self.company), "version": version,
                "nodes": size[0]["nodes"] if size else 0, "edges": size[0]["edges"] if size else 0}

    def service_map(self) -> list[dict[str, Any]]:
        return run(self.graph, Q + "service_map.cypher", {})

    def org_chart(self) -> list[dict[str, Any]]:
        return run(self.graph, Q + "org.cypher", {"at": self.now()})

    def recap(self, incident_id: str) -> str:
        return WarRoom(self.graph).recap(incident_id)

    def people(self) -> dict[str, list[str]]:
        teams: dict[str, list[str]] = {t: [] for t in W.TEAMS}
        for handle, (_, team) in W.PEOPLE[self.company].items():
            teams[team].append(handle)
        return teams

    def settings(self) -> dict[str, Any]:
        return {
            "company": self.company, "graph": config.graph_name(self.company),
            "timing_profile": config.TIMING_PROFILE, "lease_ms": config.LEASE_TTL_MS,
            "heartbeat_ms": config.HEARTBEAT_MS, "model": config.LLM_MODEL or "rule-based",
            "model_status": self.model_status,
            "stories": STORIES, "breakable": self.breakable(), "teams": self.people(),
            "labels": LABELS,
        }


def timeline(tasks: list[dict[str, Any]], checkpoints: list[dict[str, Any]],
             actions: list[dict[str, Any]], head: dict[str, Any]) -> list[dict[str, Any]]:
    """Claims, checkpoints, sends and handoffs in database-clock order."""
    events: list[dict[str, Any]] = []
    for t in tasks:
        events.append({"at": t["created_at"], "kind": "created", "task": t["type"],
                       "text": f"{t['type']} task queued"})
        for i, (who, at) in enumerate(zip(t["claimed_by"] or [], t["claimed_at"] or [],
                                          strict=False)):
            events.append({"at": at, "kind": "claim" if i == 0 else "takeover",
                           "task": t["type"], "agent": who, "epoch": i + 1,
                           "text": (f"{who} claimed it" if i == 0
                                    else f"{who} took over after the lease ran out")})
        if t["done_at"]:
            events.append({"at": t["done_at"], "kind": "done", "task": t["type"],
                           "agent": t["owner"], "epoch": t["epoch"],
                           "text": f"{t['type']} done"})
    for c in checkpoints:
        args = ", ".join(f"{k}={v}" for k, v in (c["args"] or {}).items())
        events.append({"at": c["at"], "kind": "checkpoint", "task": "investigate",
                       "agent": c["agent"], "epoch": c["epoch"], "n": c["n"],
                       "text": f"step {c['n']}: {c['tool']}({args})"})
    for a in actions:
        events.append({"at": a["sent_at"] or a["created_at"], "kind": "action", "task": "respond",
                       "text": f"{a['channel']} sent to {a['recipient']} (intent {a['key']})"})
    events.sort(key=lambda e: (e["at"] or 0, {"created": 0, "claim": 1, "takeover": 1}
                               .get(e["kind"], 2)))
    with contextlib.suppress(Exception):
        start = events[0]["at"]
        for e in events:
            e["t_ms"] = e["at"] - start
    return events
