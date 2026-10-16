"""FalkorDB connection and query-file helpers.

Every query the product depends on lives in a .cypher file (the rules ask for
them in the submission). Lines starting with // are stripped before sending, so
the files can carry comments even if the engine rejects them.
"""
from __future__ import annotations

import threading
import time
from functools import cache, lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import config

if TYPE_CHECKING:
    from falkordb import FalkorDB

ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def client() -> FalkorDB:
    from falkordb import FalkorDB  # imported here so offline tests run without the driver

    return FalkorDB(host=config.FALKORDB_HOST, port=config.FALKORDB_PORT,
                    password=config.FALKORDB_PASSWORD)


def unavailable(exc: BaseException) -> bool:
    """True if `exc` means FalkorDB is down, restarting or still loading its data,
    as opposed to a bug: callers wait and retry instead of reporting a failure."""
    from redis.exceptions import BusyLoadingError
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError

    return isinstance(exc, (BusyLoadingError, RedisConnectionError, RedisTimeoutError,
                            ConnectionError))


class Outage:
    """Log a FalkorDB outage once when it starts and once when it ends."""

    def __init__(self, log: Any, who: str) -> None:
        self.log, self.who, self.down = log, who, False

    def failed(self) -> None:
        if not self.down:
            self.log.warning("%s: FalkorDB unavailable (restarting?); waiting", self.who)
        self.down = True

    def ok(self) -> None:
        if self.down:
            self.log.info("%s: FalkorDB is back", self.who)
        self.down = False


def wait_ready(timeout_s: float = 60.0, log: Any = print) -> bool:
    """Wait until FalkorDB answers graph commands.

    Right after a restart it replies "LOADING" while it reads the dataset back from
    disk (AOF/RDB); commands sent then fail. Returns False if it is still not ready
    after `timeout_s` (or not reachable at all)."""
    from redis.exceptions import BusyLoadingError
    from redis.exceptions import ConnectionError as RedisConnectionError

    deadline = time.monotonic() + timeout_s
    told = False
    while True:
        try:
            client().connection.execute_command("GRAPH.LIST")
            return True
        except (BusyLoadingError, RedisConnectionError) as e:
            if time.monotonic() > deadline:
                return False
            if not told:
                log(f"waiting for FalkorDB ({'loading its data from disk' if isinstance(e, BusyLoadingError) else 'not reachable yet'})...")
                told = True
            time.sleep(0.5)


def graph(company_id: str):
    """Graph handle for a trusted company id (see config.graph_name)."""
    return client().select_graph(config.graph_name(company_id))


def raw_graph(name: str):
    """Graph handle by explicit name. Only for eval arms and tests, never for agents."""
    return client().select_graph(name)


@cache
def load_query(relpath: str) -> str:
    """Load e.g. 'coord/queries/claim.cypher' with // comment lines removed."""
    text = (ROOT / relpath).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]
    return "\n".join(lines).strip()


class Timings:
    """Optional per-query latency recorder (the load benchmark switches it on)."""

    def __init__(self) -> None:
        self.samples: list[tuple[str, float]] = []
        self._lock = threading.Lock()

    def add(self, relpath: str, seconds: float) -> None:
        with self._lock:
            self.samples.append((relpath, seconds))


_timings: Timings | None = None


def record_timings(timings: Timings | None) -> None:
    """Start (or, with None, stop) recording how long each query file takes."""
    global _timings
    _timings = timings


def run(g: Any, relpath: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a query file and return rows as dicts keyed by column name."""
    started = time.perf_counter() if _timings is not None else 0.0
    res = g.query(load_query(relpath), params or {})
    header = [h[1] if isinstance(h, (list, tuple)) else h for h in (res.header or [])]
    rows = [dict(zip(header, row, strict=True)) for row in (res.result_set or [])]
    if _timings is not None:
        _timings.add(relpath, time.perf_counter() - started)
    return rows
