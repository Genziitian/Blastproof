"""Where the integration suites run: FalkorDB when it is up, the graph double always.

Each integration suite is written once as a mixin and run on both backends:

    class GateG1OnDouble(GateG1Cases, unittest.TestCase): backend = staticmethod(double)

    @unittest.skipUnless(falkordb_up(), SKIP_REASON)
    class GateG1OnFalkorDB(GateG1Cases, unittest.TestCase): backend = staticmethod(falkordb)

The double checks that Python and the .cypher files agree (parameters, columns,
property types) and runs the whole flow offline. Only the FalkorDB run proves the
Cypher itself.
"""
from __future__ import annotations

import contextlib
from typing import Any

from common.db import client, raw_graph
from tests.graph_double import GraphDouble

SKIP_REASON = "FalkorDB not reachable on FALKORDB_HOST:FALKORDB_PORT"


def falkordb_up() -> bool:
    try:
        client().connection.ping()
        return True
    except Exception:
        return False


def falkordb(name: str) -> Any:
    """An empty scratch graph on the running FalkorDB."""
    with contextlib.suppress(Exception):
        raw_graph(name).delete()
    return raw_graph(name)


def double(name: str) -> GraphDouble:
    return GraphDouble(name)


def expire_lease(g: Any, task_id: str) -> None:
    """Make a task's lease run out now, as if its worker had stalled."""
    g.query("MATCH (t:Task {id: $id}) SET t.lease_until = timestamp() - 1", {"id": task_id})


def count(g: Any, label: str, **props: Any) -> int:
    where = "".join(f" AND n.{k} = ${k}" for k in props)
    return g.query(f"MATCH (n:{label}) WHERE true{where} RETURN count(n)",
                   props).result_set[0][0]
