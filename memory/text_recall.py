"""Arm B: text retrieval over the same memory records (the plan's fair baseline).

Which memories to try is decided by cosine similarity between the incident's alert
text and each playbook's text (FalkorDB `vec.cosineDistance`, exact). Everything after
that is shared with graph recall: the same records, validity and trust rules, the
same precondition executor and the same feedback. Only retrieval differs.

What text retrieval cannot know is where in the system a memory applies, so each
retrieved playbook is tried against the nodes it is pinned to and, for datastore
playbooks, every datastore of its kind: the same transfer scope as graph recall
(A1b), without knowing which of them is near the alerting services. A path from an
alerting service to each target is looked up only to bind `$alerting` and
`$caller` for the checks.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from common.db import run
from memory.embed import Embedder
from memory.recall import TOP_K, Recalled

Q = "memory/queries/"
CANDIDATES = 10  # nearest memories fetched before validity filtering


def playbook_text(row: dict[str, Any]) -> str:
    about = ", ".join(sorted(row["about"] or []))
    alerts = "; ".join(sorted(row["alerts"] or []))
    return (f"{row['signature']} {row['family'].replace('_', ' ')} on {row['kind']}. "
            f"Pinned to {about}. Learned from alerts: {alerts}")


def index_playbooks(graph: Any, embedder: Embedder) -> int:
    """Embed every playbook whose text changed since it was last embedded."""
    stale = []
    for row in run(graph, Q + "playbook_texts.cypher", {}):
        text = playbook_text(row)
        digest = hashlib.sha256(f"{embedder.name}|{text}".encode()).hexdigest()[:16]
        if row["embed_hash"] != digest:
            stale.append((row["id"], text, digest))
    if not stale:
        return 0
    vectors = embedder.embed([text for _, text, _ in stale])
    for (memory_id, _, digest), vector in zip(stale, vectors, strict=True):
        run(graph, Q + "set_embedding.cypher", {"id": memory_id, "vector": vector,
                                                 "hash": digest})
    return len(stale)


def _bind_path(graph: Any, alerting: Sequence[str], target: str) -> tuple[str, ...] | None:
    paths = [tuple(r["path"]) for r in run(graph, Q + "bind_path.cypher",
                                           {"alerting": list(alerting), "target": target})]
    return min(paths, key=lambda p: (len(p), p)) if paths else None


def recall(graph: Any, embedder: Embedder, alerting: Sequence[str], alert_texts: Sequence[str],
           scenario_now: int, k: int = TOP_K) -> list[Recalled]:
    index_playbooks(graph, embedder)
    [query] = embedder.embed([" ".join(sorted(alert_texts)) or " ".join(alerting)])
    hits = run(graph, Q + "vector_recall.cypher", {
        "k": CANDIDATES, "vector": query, "scenario_now": scenario_now})
    out: list[Recalled] = []
    for hit in sorted(hits, key=lambda h: (h["distance"], h["id"])):
        targets = list(dict.fromkeys(sorted(hit["about"] or [])))
        if hit["kind"] != "service":
            targets += [d["name"] for d in run(graph, Q + "datastores_of_kind.cypher",
                                               {"kind": hit["kind"]}) if d["name"] not in targets]
        similarity = round(1.0 - float(hit["distance"]), 6)
        for target in targets:
            path = _bind_path(graph, alerting, target)
            if path is None:
                continue
            out.append(Recalled(hit["id"], target, similarity, float(hit["trust"]),
                                len(path) - 1, path, target not in (hit["about"] or [])))
            if len(out) == k:
                return out
    return out
