"""FalkorDB connection and query-file helpers.

Every query the product depends on lives in a .cypher file (the rules ask for
them in the submission). Lines starting with // are stripped before sending, so
the files can carry comments even if the engine rejects them.
"""
from __future__ import annotations

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


def run(g: Any, relpath: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run a query file and return rows as dicts keyed by column name."""
    res = g.query(load_query(relpath), params or {})
    header = [h[1] if isinstance(h, (list, tuple)) else h for h in (res.header or [])]
    return [dict(zip(header, row, strict=True)) for row in (res.result_set or [])]
