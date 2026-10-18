"""Investigator processes the UI can start and kill (SIGKILL, for real).

Each is `python -m scripts.run_worker --forever`, reading evidence from the shared
scenario store. They share nothing with each other or with the UI except FalkorDB.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from common import config

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Proc:
    name: str
    popen: subprocess.Popen[str] | None = None
    started_at: float | None = None
    ended_at: float | None = None
    exit_code: int | None = None
    killed: bool = False
    log: deque[str] = field(default_factory=lambda: deque(maxlen=200))

    def alive(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def view(self) -> dict[str, Any]:
        if self.popen is not None and not self.alive() and self.ended_at is None:
            self.ended_at = time.time()
            self.exit_code = self.popen.returncode
        return {
            "name": self.name, "alive": self.alive(),
            "pid": self.popen.pid if self.popen else None,
            "started_at": self.started_at, "ended_at": self.ended_at,
            "exit_code": self.exit_code, "killed": self.killed,
            "log": list(self.log)[-12:],
        }


class Supervisor:
    def __init__(self, company: str, world_dir: Path, names: tuple[str, ...] = ("inv-1", "inv-2"),
                 pace_s: float = 1.5) -> None:
        self.company = company
        self.world_dir = world_dir
        self.pace_s = pace_s
        self.procs = {n: Proc(n) for n in names}
        self._lock = threading.Lock()

    def start(self, name: str) -> dict[str, Any]:
        with self._lock:
            p = self.procs[name]
            if p.alive():
                return p.view()
            cmd = [sys.executable, "-u", "-m", "scripts.run_worker", "--company", self.company,
                   "--world", str(self.world_dir), "--forever", "--instance", name,
                   "--pace", str(self.pace_s), "--exit-with-parent"]
            env = os.environ.copy()
            if config.PUBLIC_MODE and not env.get("PUBLIC_LLM"):
                env["LLM_MODEL"] = ""  # a public demo never calls a model (beats .env)
            p.popen = subprocess.Popen(cmd, cwd=ROOT, env=env, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            p.started_at, p.ended_at, p.exit_code, p.killed = time.time(), None, None, False
            p.log.append(f"started pid {p.popen.pid}")
            assert p.popen.stdout is not None
            threading.Thread(target=self._pump, args=(p, p.popen.stdout), daemon=True).start()
            return p.view()

    def kill(self, name: str) -> dict[str, Any]:
        """SIGKILL: no cleanup, no lease release. The lease simply runs out.

        Popen.kill() is SIGKILL on POSIX and TerminateProcess on Windows: a hard
        kill on both, with no chance for the worker to clean up."""
        with self._lock:
            p = self.procs[name]
            if p.alive() and p.popen is not None:
                p.popen.kill()
                p.popen.wait(timeout=5)
                p.killed, p.ended_at, p.exit_code = True, time.time(), p.popen.returncode
                p.log.append(f"SIGKILL pid {p.popen.pid} (exit {p.popen.returncode})")
            return p.view()

    def start_all(self) -> None:
        for name in self.procs:
            self.start(name)

    def stop_all(self) -> None:
        with self._lock:
            for p in self.procs.values():
                if p.alive() and p.popen is not None:
                    p.popen.terminate()
            for p in self.procs.values():
                if p.popen is not None:
                    try:
                        p.popen.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        p.popen.kill()

    def view(self) -> list[dict[str, Any]]:
        return [p.view() for p in self.procs.values()]

    @staticmethod
    def _pump(p: Proc, stream: IO[str]) -> None:
        for line in stream:
            p.log.append(line.rstrip()[-240:])
