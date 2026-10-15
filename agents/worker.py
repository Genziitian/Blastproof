"""The loop every agent runs: claim a task, hold its lease, do the work, hand off.

A heartbeat thread extends the lease while the task runs. If any fenced write or
heartbeat reports `lease_lost`, the worker stops that task immediately: another
worker owns it now, and the fence guard would reject our writes anyway.
"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any

from common import config
from coord import tasks
from coord.tasks import Lease, Outcome, Result


class LeaseLost(RuntimeError):
    pass


class Heartbeat:
    def __init__(self, graph: Any, lease: Lease, interval_ms: int) -> None:
        self._graph = graph
        self._lease = lease
        self._interval_s = interval_ms / 1000
        self._stop = threading.Event()
        self.lost = threading.Event()
        self._thread = threading.Thread(target=self._beat, name=f"heartbeat-{lease.task_id}",
                                        daemon=True)

    def _beat(self) -> None:
        while not self._stop.wait(self._interval_s):
            if tasks.heartbeat(self._graph, self._lease).outcome is Outcome.LEASE_LOST:
                self.lost.set()
                return

    def __enter__(self) -> Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval_s + 1)


class Worker(ABC):
    task_type: str

    def __init__(self, graph: Any, instance: str) -> None:
        self.graph = graph
        self.instance = instance
        self.log = logging.getLogger(f"{type(self).__name__.lower()}[{instance}]")
        self._heartbeat: Heartbeat | None = None

    @abstractmethod
    def handle(self, lease: Lease) -> None: ...

    def run_once(self) -> bool:
        """Claim and process one task. Returns False if nothing was claimable."""
        claimed, lease = tasks.claim(self.graph, self.task_type, self.instance)
        if lease is None:
            return False
        self.log.info("claimed %s (epoch %s, attempt %s)", lease.task_id, lease.epoch,
                      claimed.data.get("attempts"))
        with Heartbeat(self.graph, lease, config.HEARTBEAT_MS) as hb:
            self._heartbeat = hb
            try:
                self.handle(lease)
            except LeaseLost:
                self.log.warning("lost the lease on %s; stopping", lease.task_id)
            finally:
                self._heartbeat = None
        return True

    def run_forever(self, stop: threading.Event, poll_s: float = 1.0) -> None:
        while not stop.is_set():
            if not self.run_once():
                stop.wait(poll_s)

    def check_lease(self) -> None:
        """Call before starting any slow step."""
        if self._heartbeat is not None and self._heartbeat.lost.is_set():
            raise LeaseLost

    @staticmethod
    def require(result: Result) -> Result:
        if result.outcome is Outcome.LEASE_LOST:
            raise LeaseLost
        return result
