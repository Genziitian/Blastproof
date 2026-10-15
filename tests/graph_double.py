"""An in-memory stand-in for one FalkorDB graph, for running the whole flow offline.

It does not parse Cypher. Each product query file has a Python twin below that
does what the Cypher says. What it does check, on every call, is the contract
between the Python code and the real .cypher text:

- every `$param` the query uses is supplied (FalkorDB rejects a missing one);
- no parameter is supplied that the query never reads (usually a typo);
- every row has exactly the query's RETURN columns, in order;
- every stored property is a value FalkorDB accepts (no maps, no nulls in lists).

So a renamed column, a misspelt parameter or a map-valued property fails here
first. What it cannot catch is Cypher FalkorDB itself rejects; that is what
`make test-live` is for.
"""
from __future__ import annotations

import itertools
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from common.db import ROOT, load_query


class ContractError(AssertionError):
    pass


# --------------------------------------------------------------------------- store

@dataclass
class Node:
    id: int
    labels: set[str]
    props: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.props.get(key, default)


@dataclass
class Edge:
    src: int
    type: str
    dst: int
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    header: list[list[Any]]
    result_set: list[list[Any]]


def _legal(value: Any, where: str) -> None:
    if isinstance(value, dict):
        raise ContractError(f"{where}: maps cannot be property values; store JSON")
    if isinstance(value, (list, tuple)):
        for v in value:
            if v is None or isinstance(v, (dict, list, tuple)):
                raise ContractError(f"{where}: arrays may hold only scalars, got {v!r}")
    elif not isinstance(value, (str, int, float, bool)):
        raise ContractError(f"{where}: unsupported property type {type(value).__name__}")


# ----------------------------------------------------------------- query contract

PARAM = re.compile(r"\$([A-Za-z_]\w*)")
CLAUSE_END = re.compile(r"\b(ORDER\s+BY|SKIP|LIMIT)\b", re.IGNORECASE)


def _strip_strings(text: str) -> str:
    return re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", text)


def _split_top(text: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def return_columns(cypher: str) -> list[str]:
    """Column names of the final RETURN clause ([] if the query returns nothing)."""
    text = _strip_strings(cypher)
    matches = list(re.finditer(r"\bRETURN\b", text, re.IGNORECASE))
    if not matches:
        return []
    body = text[matches[-1].end():]
    end = CLAUSE_END.search(body)
    body = body[:end.start()] if end else body
    body = re.sub(r"^\s*DISTINCT\b", "", body, flags=re.IGNORECASE)
    cols = []
    for item in _split_top(body):
        m = re.search(r"\bAS\s+(\w+)\s*$", item, re.IGNORECASE)
        cols.append(m.group(1) if m else item)
    return cols


def query_params(cypher: str) -> set[str]:
    return set(PARAM.findall(_strip_strings(cypher)))


# --------------------------------------------------------------------- the graph

Impl = Callable[["GraphDouble", dict[str, Any]], list[dict[str, Any]]]
IMPLS: dict[str, Impl] = {}
INLINE: list[tuple[re.Pattern[str], Impl]] = []


def implements(relpath: str) -> Callable[[Impl], Impl]:
    def register(fn: Impl) -> Impl:
        IMPLS[relpath] = fn
        return fn
    return register


def inline(pattern: str) -> Callable[[Impl], Impl]:
    def register(fn: Impl) -> Impl:
        INLINE.append((re.compile(pattern, re.DOTALL), fn))
        return fn
    return register


def _norm(text: str) -> str:
    return " ".join(text.split())


class GraphDouble:
    """One company graph. `clock_ms` plays the database's timestamp()."""

    _by_text: ClassVar[dict[str, str] | None] = None
    exercised: ClassVar[set[str]] = set()  # query files run by any double in this process

    def __init__(self, name: str = "double", clock_ms: int = 1_000_000) -> None:
        self.name = name
        self.clock_ms = clock_ms
        self.nodes: dict[int, Node] = {}
        self.edges: list[Edge] = []
        self.calls: list[str] = []
        self.unused_params: list[tuple[str, set[str]]] = []
        self._ids = itertools.count(1)
        self._lock = threading.RLock()

    # -- falkordb.Graph surface
    def query(self, cypher: str, params: dict[str, Any] | None = None) -> Result:
        params = dict(params or {})
        with self._lock:
            self.clock_ms += 1  # timestamp() moves on between queries, like a real clock
            relpath = self._lookup(cypher)
            missing = query_params(cypher) - params.keys()
            if missing:
                raise ContractError(f"{relpath}: missing parameters {sorted(missing)}")
            extra = params.keys() - query_params(cypher)
            if extra:
                self.unused_params.append((relpath, set(extra)))
            if relpath == "<inline>" and _norm(cypher).startswith("MATCH (n:") \
                    and _norm(cypher).endswith("RETURN count(n)"):
                rows = _count_query(self, _norm(cypher), params)
            else:
                rows = (IMPLS.get(relpath) or self._inline(cypher))(self, params)
            cols = return_columns(cypher)
            for row in rows:
                if list(row) != cols:
                    raise ContractError(f"{relpath}: row columns {list(row)} != RETURN {cols}")
            self.calls.append(relpath)
            GraphDouble.exercised.add(relpath)
            return Result([[1, c] for c in cols], [[r[c] for c in cols] for r in rows])

    def delete(self) -> None:
        self.nodes.clear()
        self.edges.clear()

    def advance(self, ms: int) -> None:
        with self._lock:
            self.clock_ms += ms

    # -- dispatch
    @classmethod
    def _query_files(cls) -> dict[str, str]:
        if cls._by_text is None:
            cls._by_text = {}
            for path in ROOT.glob("*/queries/*.cypher"):
                rel = str(path.relative_to(ROOT))
                cls._by_text[_norm(load_query(rel))] = rel
            missing = set(cls._by_text.values()) - IMPLS.keys()
            if missing:
                raise ContractError(f"query files without a twin: {sorted(missing)}")
        return cls._by_text

    def _lookup(self, cypher: str) -> str:
        return self._query_files().get(_norm(cypher), "<inline>")

    def _inline(self, cypher: str) -> Impl:
        text = _norm(cypher)
        for pattern, fn in INLINE:
            if pattern.fullmatch(text):
                return fn
        raise ContractError(f"no twin for inline query: {text[:120]}")

    # -- store helpers
    def find(self, label: str | None = None, **props: Any) -> list[Node]:
        return [n for n in self.nodes.values()
                if (label is None or label in n.labels)
                and all(n.props.get(k) == v for k, v in props.items())]

    def one(self, label: str | None = None, **props: Any) -> Node | None:
        found = self.find(label, **props)
        return found[0] if found else None

    def entity(self, name: str) -> Node | None:
        """A Service or Datastore by name."""
        return next((n for n in self.nodes.values()
                     if n.labels & {"Service", "Datastore"} and n.get("name") == name), None)

    def create(self, labels: Iterable[str], props: dict[str, Any]) -> Node:
        node = Node(next(self._ids), set(labels), {})
        self.set(node, props)
        self.nodes[node.id] = node
        return node

    def merge(self, labels: Iterable[str], key: dict[str, Any],
              on_create: dict[str, Any] | None = None) -> Node:
        labels = list(labels)
        found = self.find(labels[0], **key)
        found = [n for n in found if set(labels) <= n.labels]
        if found:
            return found[0]
        return self.create(labels, {**key, **(on_create or {})})

    @staticmethod
    def set(target: Node | Edge, props: dict[str, Any]) -> None:
        for k, v in props.items():
            if v is None:  # SET x.p = null removes the property
                target.props.pop(k, None)
                continue
            _legal(v, f"property {k}")
            target.props[k] = list(v) if isinstance(v, tuple) else v

    def out(self, node: Node, rel: str) -> list[tuple[Edge, Node]]:
        return [(e, self.nodes[e.dst]) for e in self.edges if e.src == node.id and e.type == rel]

    def into(self, node: Node, rel: str) -> list[tuple[Edge, Node]]:
        return [(e, self.nodes[e.src]) for e in self.edges if e.dst == node.id and e.type == rel]

    def merge_edge(self, src: Node, rel: str, dst: Node,
                   props: dict[str, Any] | None = None) -> tuple[Edge, bool]:
        props = props or {}
        for e in self.edges:
            if (e.src, e.type, e.dst) == (src.id, rel, dst.id) and all(
                    e.props.get(k) == v for k, v in props.items()):
                return e, False
        edge = Edge(src.id, rel, dst.id)
        self.set(edge, props)
        self.edges.append(edge)
        return edge, True

    def paths(self, start: Node, rel: str, lo: int, hi: int) -> list[list[Node]]:
        """Every path start -[rel*lo..hi]-> x with no repeated edge."""
        found: list[list[Node]] = []

        def walk(path: list[Node], used: set[int]) -> None:
            if len(path) - 1 >= lo:
                found.append(path)
            if len(path) - 1 == hi:
                return
            for i, e in enumerate(self.edges):
                if e.src == path[-1].id and e.type == rel and i not in used:
                    walk([*path, self.nodes[e.dst]], used | {i})

        walk([start], set())
        return found

    def guarded(self, p: dict[str, Any]) -> Node | None:
        """The fence guard every task write uses."""
        t = self.one("Task", id=p["task_id"])
        if t and t.get("status") == "leased" and t.get("epoch") == p["epoch"] \
                and t.get("lease_owner") == p["instance"] \
                and t.get("lease_until", -1) >= self.clock_ms:
            return t
        return None

    def incident_of(self, task: Node) -> Node | None:
        return next((i for _, i in self.out(task, "FOR") if "Incident" in i.labels), None)


def _valid(m: Node, now: int) -> bool:
    return (m.get("status") == "active" and m.get("recorded_at", now + 1) <= now
            and m.get("valid_from", now + 1) <= now
            and (m.get("valid_to") is None or now < m.get("valid_to")))


# ===================================================================== coord/

@implements("coord/queries/create_task.cypher")
def _create_task(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    i = g.one("Incident", key=p["incident_key"])
    if i is None:
        return []
    t = g.merge(["Task"], {"id": p["task_id"]}, {
        "type": p["type"], "status": "open", "epoch": 0, "attempts": 0,
        "created_at": g.clock_ms})
    g.merge_edge(t, "FOR", i)
    return [{"id": t.get("id"), "status": t.get("status")}]


@implements("coord/queries/claim.cypher")
def _claim(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    now = g.clock_ms
    ready = [t for t in g.find("Task", type=p["type"])
             if (t.get("status") == "open"
                 or (t.get("status") == "leased" and t.get("lease_until") < now))
             and t.get("attempts") < p["max_attempts"]]
    if not ready:
        return []
    t = min(ready, key=lambda t: t.get("created_at"))
    g.set(t, {"status": "leased", "lease_owner": p["instance"],
              "lease_until": now + p["ttl_ms"], "attempts": t.get("attempts") + 1,
              "epoch": t.get("epoch") + 1})
    return [{"id": t.get("id"), "epoch": t.get("epoch"), "attempts": t.get("attempts")}]


@implements("coord/queries/heartbeat.cypher")
def _heartbeat(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.guarded(p)
    if t is None:
        return []
    g.set(t, {"lease_until": g.clock_ms + p["ttl_ms"]})
    return [{"id": t.get("id"), "lease_until": t.get("lease_until")}]


@implements("coord/queries/checkpoint.cypher")
def _checkpoint(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.guarded(p)
    if t is None:
        return []
    c = g.merge(["Checkpoint"], {"cid": p["cid"]}, {
        "task_id": p["task_id"], "n": p["n"], "epoch": p["epoch"], "tool": p["tool"],
        "args_json": p["args_json"], "observation": p["observation"],
        "at": g.clock_ms, "scenario_at": p["scenario_now"]})
    g.merge_edge(t, "HAS_CHECKPOINT", c)
    return [{"n": c.get("n"), "written_by_epoch": c.get("epoch")}]


@implements("coord/queries/read_checkpoints.cypher")
def _read_checkpoints(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Task", id=p["task_id"])
    cs = [c for _, c in g.out(t, "HAS_CHECKPOINT") if "Checkpoint" in c.labels] if t else []
    return [{"n": c.get("n"), "tool": c.get("tool"), "args_json": c.get("args_json"),
             "observation": c.get("observation"), "epoch": c.get("epoch")}
            for c in sorted(cs, key=lambda c: c.get("n"))]


@implements("coord/queries/send_action.cypher")
def _send_action(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.guarded(p)
    if t is None:
        return []
    a = g.merge(["Action"], {"key": p["intent_key"]}, {
        "kind": p["kind"], "recipient": p["recipient"], "channel": p["channel"],
        "payload": p["payload_json"], "status": "pending", "created_at": g.clock_ms})
    g.merge_edge(t, "EMITTED", a)
    before = a.get("status")
    g.set(a, {"status": "sent", "sent_at": a.get("sent_at") or g.clock_ms})
    return [{"key": a.get("key"), "before": before, "recipient": a.get("recipient"),
             "channel": a.get("channel")}]


@implements("coord/queries/read_action.cypher")
def _read_action(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    a = g.one("Action", key=p["intent_key"])
    return [{"key": a.get("key"), "status": a.get("status"), "recipient": a.get("recipient"),
             "channel": a.get("channel")}] if a else []


@implements("coord/queries/handoff.cypher")
def _handoff(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.guarded(p)
    i = g.incident_of(t) if t else None
    if t is None or i is None:
        return []
    g.set(t, {"status": "done", "done_at": g.clock_ms})
    n = g.merge(["Task"], {"id": p["task_id"] + ":next"}, {
        "type": p["next_type"], "status": "open", "epoch": 0, "attempts": 0,
        "created_at": g.clock_ms})
    g.merge_edge(t, "NEXT", n)
    g.merge_edge(n, "FOR", i)
    return [{"next_id": n.get("id")}]


@implements("coord/queries/read_task.cypher")
def _read_task(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Task", id=p["task_id"])
    if t is None:
        return []
    nxt: list[Node | None] = [n for _, n in g.out(t, "NEXT") if "Task" in n.labels]
    return [{"status": t.get("status"), "epoch": t.get("epoch"),
             "lease_owner": t.get("lease_owner"), "next_id": n.get("id") if n else None}
            for n in (nxt or [None])]


@implements("coord/queries/complete.cypher")
def _complete(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.guarded(p)
    if t is None:
        return []
    g.set(t, {"status": "done", "done_at": g.clock_ms})
    return [{"id": t.get("id")}]


@implements("coord/queries/stuck_sweep.cypher")
def _stuck_sweep(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for t in g.find("Task", status="leased"):
        if t.get("lease_until") < g.clock_ms and t.get("attempts") >= p["max_attempts"]:
            g.set(t, {"status": "stuck"})
            out.append({"id": t.get("id")})
    return out


# ==================================================================== agents/

@implements("agents/queries/open_incident.cypher")
def _open_incident(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    i = g.merge(["Incident"], {"key": p["incident_key"]}, {
        "id": p["incident_id"], "status": "open", "observed_at": p["observed_at"],
        "opened_at": g.clock_ms})
    count = 0
    for al in p["alerts"]:
        for field_ in ("service", "key", "signal", "text", "fired_at"):
            if field_ not in al:
                raise ContractError(f"open_incident: alert map has no {field_!r}")
        for s in g.find("Service", name=al["service"]):
            a = g.merge(["Alert"], {"key": al["key"]}, {
                "signal": al["signal"], "text": al["text"], "fired_at": al["fired_at"]})
            g.merge_edge(a, "FIRED_ON", s)
            g.merge_edge(a, "PART_OF", i)
            g.merge_edge(i, "TOUCHED", s, {"role": "alerting"})
            count += 1
    return [{"alerts": count}]


@implements("agents/queries/incident_context.cypher")
def _incident_context(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Task", id=p["task_id"])
    i = g.incident_of(t) if t else None
    if i is None:
        return []
    alerting: list[str] = []
    for _, a in g.into(i, "PART_OF"):
        for _, s in g.out(a, "FIRED_ON"):
            if "Service" in s.labels and s.get("name") not in alerting:
                alerting.append(s.get("name"))
    return [{"incident_key": i.get("key"), "incident_id": i.get("id"),
             "observed_at": i.get("observed_at"), "alerting": alerting}]


@implements("agents/queries/record_decision.cypher")
def _record_decision(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.guarded(p)
    i = g.incident_of(t) if t else None
    if t is None or i is None:
        return []
    d = g.merge(["Decision"], {"id": p["decision_id"]}, {
        "kind": "root_cause", "root": p["root"], "family": p["family"],
        "summary": p["summary"], "evidence_steps": p["evidence_steps"],
        "agent": p["instance"], "task_id": p["task_id"], "epoch": p["epoch"],
        "at": g.clock_ms, "scenario_at": p["scenario_now"]})
    g.merge_edge(d, "FOR", i)
    g.set(i, {"status": "diagnosed"})
    return [{"id": d.get("id"), "written_by_epoch": d.get("epoch")}]


@implements("agents/queries/record_usage.cypher")
def _record_usage(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    d = g.one("Decision", id=p["decision_id"])
    if g.guarded(p) is None or d is None:
        return []
    out = []
    for u in p["used"]:
        m = g.one("Memory", id=u["id"])
        if m is None:
            continue
        r, created = g.merge_edge(d, "USED", m, {"target": u["target"]})
        if created:
            g.set(r, {"score": u["score"], "hops": u["hops"], "path": u["path"],
                      "trust_at_use": u["trust"], "applied": u["applied"],
                      "checks_json": u["checks_json"]})
        out.append({"id": m.get("id"), "target": r.props.get("target")})
    return out


def _decision_for(g: GraphDouble, i: Node) -> Node | None:
    ds = [d for _, d in g.into(i, "FOR")
          if "Decision" in d.labels and d.get("kind") == "root_cause"]
    return max(ds, key=lambda d: d.get("at")) if ds else None


@implements("agents/queries/respond_context.cypher")
def _respond_context(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Task", id=p["task_id"])
    i = g.incident_of(t) if t else None
    d = _decision_for(g, i) if i else None
    if i is None or d is None:
        return []
    return [{"incident_key": i.get("key"), "incident_id": i.get("id"),
             "observed_at": i.get("observed_at"), "decision_id": d.get("id"),
             "root": d.get("root"), "family": d.get("family"), "summary": d.get("summary"),
             "evidence_steps": d.get("evidence_steps")}]


def _review(g: GraphDouble, p: dict[str, Any], verdict: str) -> list[dict[str, Any]]:
    t = g.guarded(p)
    i = g.incident_of(t) if t else None
    d = g.one("Decision", id=p["decision_id"])
    if t is None or i is None or d is None:
        return []
    root = g.entity(d.get("root"))
    if verdict == "confirmed" and root is None:
        return []  # MATCH (root) found nothing: the whole write is skipped
    f = g.merge(["Feedback"], {"id": p["feedback_id"]},
                {"verdict": verdict, "by": p["by"], "at": g.clock_ms})
    g.merge_edge(f, "ON", d)
    if verdict == "confirmed" and root is not None:
        g.merge_edge(i, "TOUCHED", root, {"role": "root"})
        g.set(i, {"status": "resolved", "resolved_at": p["scenario_now"],
                  "signature": f"{d.get('family')}:{root.get('kind') or 'service'}"})
    else:
        g.set(i, {"status": "needs_review"})
    g.set(t, {"status": "done", "done_at": g.clock_ms})
    learn = g.merge(["Task"], {"id": p["learn_task_id"]}, {
        "type": "learn", "status": "open", "epoch": 0, "attempts": 0,
        "created_at": g.clock_ms})
    g.merge_edge(learn, "FOR", i)
    return [{"learn_task_id": learn.get("id")}]


@implements("agents/queries/confirm.cypher")
def _confirm(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return _review(g, p, "confirmed")


@implements("agents/queries/reject.cypher")
def _reject(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return _review(g, p, "rejected")


@implements("agents/queries/learn_context.cypher")
def _learn_context(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Task", id=p["task_id"])
    i = g.incident_of(t) if t else None
    d = _decision_for(g, i) if i else None
    f = next((f for _, f in g.into(d, "ON") if "Feedback" in f.labels), None) if d else None
    if i is None or d is None or f is None:
        return []
    root = g.entity(d.get("root"))
    return [{"incident_key": i.get("key"), "observed_at": i.get("observed_at"),
             "decision_id": d.get("id"), "root": d.get("root"), "family": d.get("family"),
             "investigate_task": d.get("task_id"), "verdict": f.get("verdict"),
             "root_kind": (root.get("kind") if root else None) or "service"}]


def _usage(g: GraphDouble, d: Node) -> list[tuple[Edge, Node]]:
    return [(e, m) for e, m in g.out(d, "USED") if "Memory" in m.labels]


@implements("agents/queries/decision_usage.cypher")
def _decision_usage(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    d = g.one("Decision", id=p["decision_id"])
    return [{"id": m.get("id"), "target": e.props.get("target"), "applied": e.props.get("applied"),
             "verdict": e.props.get("verdict")} for e, m in (_usage(g, d) if d else [])]


def _incident_tasks(g: GraphDouble, key: str) -> tuple[Node | None, list[Node]]:
    i = g.one("Incident", key=key)
    return i, ([t for _, t in g.into(i, "FOR") if "Task" in t.labels] if i else [])


@implements("agents/queries/incident_report.cypher")
def _incident_report(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    _, ts = _incident_tasks(g, p["incident_key"])
    return [{"task": t.get("id"), "type": t.get("type"), "status": t.get("status"),
             "created_at": t.get("created_at"),
             "checkpoints": len(g.out(t, "HAS_CHECKPOINT")), "actions": len(g.out(t, "EMITTED"))}
            for t in sorted(ts, key=lambda t: t.get("created_at"))]


@implements("agents/queries/incident_outcome.cypher")
def _incident_outcome(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    i, ts = _incident_tasks(g, p["incident_key"])
    if i is None:
        return []
    d = next((d for _, d in g.into(i, "FOR") if "Decision" in d.labels), None)
    f = next((f for _, f in g.into(d, "ON")), None) if d else None
    notified: list[str] = []
    for t in ts:
        for _, a in g.out(t, "EMITTED"):
            if a.get("recipient") not in notified:
                notified.append(a.get("recipient"))
    return [{"status": i.get("status"), "signature": i.get("signature"),
             "root": d.get("root") if d else None, "family": d.get("family") if d else None,
             "verdict": f.get("verdict") if f else None, "notified": notified}]


@implements("agents/queries/incident_memory.cypher")
def _incident_memory(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    i = g.one("Incident", key=p["incident_key"])
    rows = []
    for _, d in (g.into(i, "FOR") if i else []):
        if "Decision" in d.labels:
            rows += [{"memory": m.get("id"), "target": e.props.get("target"),
                      "applied": e.props.get("applied"), "verdict": e.props.get("verdict"),
                      "score": e.props.get("score")} for e, m in _usage(g, d)]
    return sorted(rows, key=lambda r: -r["score"])


# ==================================================================== memory/

def _recall_row(m: Node, alerting: str, target: str, path: list[str], weight: float
                ) -> dict[str, Any]:
    return {"id": m.get("id"), "alerting": alerting, "target": target, "hops": len(path) - 1,
            "path": path, "weight": weight, "trust": m.get("trust"),
            "recorded_at": m.get("recorded_at")}


def _alerting(g: GraphDouble, names: list[str]) -> list[Node]:
    return [s for s in g.find("Service") if s.get("name") in names]


@implements("memory/queries/recall_direct.cypher")
def _recall_direct(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for a in _alerting(g, p["alerting"]):
        for _, m in g.into(a, "ABOUT"):
            if "Memory" in m.labels and _valid(m, p["scenario_now"]):
                rows.append(_recall_row(m, a.get("name"), a.get("name"), [a.get("name")], 1.0))
    return rows


@implements("memory/queries/recall.cypher")
def _recall(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for a in _alerting(g, p["alerting"]):
        for path in g.paths(a, "DEPENDS_ON", 1, 2):
            for _, m in g.into(path[-1], "ABOUT"):
                if "Memory" in m.labels and _valid(m, p["scenario_now"]):
                    rows.append(_recall_row(m, a.get("name"), path[-1].get("name"),
                                            [n.get("name") for n in path], 1.0))
    return rows


@implements("memory/queries/recall_kind.cypher")
def _recall_kind(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for a in _alerting(g, p["alerting"]):
        for path in g.paths(a, "DEPENDS_ON", 1, 2):
            n = path[-1]
            if "Datastore" not in n.labels:
                continue
            for m in g.find("Playbook"):
                if "Memory" in m.labels and m.get("applies_to_kind") == n.get("kind") \
                        and _valid(m, p["scenario_now"]):
                    rows.append(_recall_row(m, a.get("name"), n.get("name"),
                                            [x.get("name") for x in path], 0.5))
    return rows


PLAYBOOK_FIELDS = ("id", "signature", "family", "applies_to_kind", "params_json",
                   "preconditions_json", "steps_json", "conclusion", "stop_if", "trust",
                   "helped", "misled")


@implements("memory/queries/playbooks_by_id.cypher")
def _playbooks_by_id(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{f: m.get(f) for f in PLAYBOOK_FIELDS}
            for m in g.find("Playbook") if "Memory" in m.labels and m.get("id") in p["ids"]]


@implements("memory/queries/playbook_by_signature.cypher")
def _playbook_by_signature(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    found = [m for m in g.find("Playbook", signature=p["signature"])
             if "Memory" in m.labels and m.get("status") == "active"]
    found.sort(key=lambda m: m.get("recorded_at"))
    return [{"id": found[0].get("id")}] if found else []


@implements("memory/queries/write_playbook.cypher")
def _write_playbook(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    i, root = g.one("Incident", key=p["incident_key"]), g.entity(p["root"])
    if i is None or root is None:
        return []
    pb = g.merge(["Memory", "Playbook"], {"id": p["id"]}, {
        "lineage_id": p["signature"], "version": 1, "signature": p["signature"],
        "family": p["family"], "applies_to_kind": p["applies_to_kind"],
        "params_json": p["params_json"], "preconditions_json": p["preconditions_json"],
        "steps_json": p["steps_json"], "conclusion": p["conclusion"], "stop_if": p["stop_if"],
        "payload_hash": p["payload_hash"], "source": "agent",
        "valid_from": p["scenario_now"], "recorded_at": p["scenario_now"], "status": "active",
        "helped": 0, "misled": 0, "prior_a": 1, "prior_b": 1, "trust": 0.5})
    g.merge_edge(pb, "ABOUT", root)
    g.merge_edge(pb, "LEARNED_FROM", i)
    return [{"id": pb.get("id"), "payload_hash": pb.get("payload_hash")}]


@implements("memory/queries/add_provenance.cypher")
def _add_provenance(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    pb, i = g.one("Playbook", id=p["id"]), g.one("Incident", key=p["incident_key"])
    if pb is None or i is None:
        return []
    g.merge_edge(pb, "LEARNED_FROM", i)
    return [{"id": pb.get("id")}]


@implements("memory/queries/feedback.cypher")
def _feedback(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    d = g.one("Decision", id=p["decision_id"])
    out = []
    for v in (p["verdicts"] if d else []):
        for e, m in _usage(g, d):  # type: ignore[arg-type]
            if (e.props.get("target"), m.get("id")) != (v["target"], v["id"]) \
                    or "verdict" in e.props:
                continue
            g.set(e, {"verdict": v["verdict"]})
            g.set(m, {"helped": m.get("helped") + (v["verdict"] == "helped"),
                      "misled": m.get("misled") + (v["verdict"] == "misled")})
            g.set(m, {"trust": (m.get("helped") + m.get("prior_a")) * 1.0
                      / (m.get("helped") + m.get("misled") + m.get("prior_a") + m.get("prior_b"))})
            if m.get("misled") >= 2 and m.get("trust") < 0.5:
                g.set(m, {"status": "retired"})
            out.append({"id": m.get("id"), "target": e.props.get("target"),
                        "verdict": e.props.get("verdict"), "trust": m.get("trust"),
                        "status": m.get("status")})
    return out


def _keyed(g: GraphDouble, key: str) -> Node | None:
    return next((n for n in g.nodes.values() if n.get("key") == key), None)


@implements("memory/queries/fact_check.cypher")
def _fact_check(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    existing = g.one("Memory", id=p["id"])
    versions = [f for f in g.find("Fact", lineage_id=p["lineage"]) if "Memory" in f.labels]
    return [{"scope_ok": _keyed(g, p["scope_key"]) is not None,
             "source_ok": _keyed(g, p["source_key"]) is not None,
             "existing_hash": existing.get("payload_hash") if existing else None,
             "versions": len(versions)}]


@implements("memory/queries/fact_supersede.cypher")
def _fact_supersede(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    scope, src = _keyed(g, p["scope_key"]), _keyed(g, p["source_key"])
    if scope is None or src is None:
        return []
    new = g.merge(["Memory", "Fact"], {"id": p["id"]}, {
        "lineage_id": p["lineage"], "version": p["version"], "subject": p["s"],
        "predicate": p["p"], "condition_family": p["cond"], "object": p["o"],
        "source": p["source_kind"], "approved_by": p["approver"],
        "valid_from": p["valid_from"], "recorded_at": p["scenario_now"], "status": "active",
        "helped": 0, "misled": 0, "prior_a": p["a"], "prior_b": p["b"],
        "trust": p["a"] * 1.0 / (p["a"] + p["b"]), "payload_hash": p["hash"]})
    g.merge_edge(new, "ABOUT", scope)
    g.merge_edge(new, "LEARNED_FROM", src)
    for old in g.find("Fact", lineage_id=p["lineage"]):
        if old.get("id") != new.get("id") and old.get("status") == "active" and (
                old.get("valid_to") is None or old.get("valid_to") > p["valid_from"]):
            g.set(old, {"valid_to": p["valid_from"]})
            g.merge_edge(new, "SUPERSEDES", old)
    return []


# ====================================================================== chat/

@implements("chat/queries/open_session.cypher")
def _open_session(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    person, i = g.one("Person", key=p["person_key"]), g.one("Incident", key=p["incident_key"])
    if person is None or i is None:
        return []
    s = g.merge(["Session"], {"id": p["session_id"]}, {"started_at": p["scenario_now"]})
    g.merge_edge(s, "WITH", person)
    g.merge_edge(s, "CONCERNS", i)
    return [{"id": s.get("id")}]


@implements("chat/queries/add_message.cypher")
def _add_message(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    s = g.one("Session", id=p["session_id"])
    if s is None:
        return []
    m = g.merge(["Message"], {"key": p["key"]},
                {"role": p["role"], "text": p["text"], "seq": p["seq"], "at": p["at"]})
    g.merge_edge(m, "IN", s)
    return [{"key": m.get("key")}]


@implements("chat/queries/preferences_for.cypher")
def _preferences_for(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    person = g.one("Person", key=p["person_key"])
    now, rows = p["scenario_now"], []
    for _, f in (g.into(person, "ABOUT") if person else []):
        if not {"Memory", "Fact"} <= f.labels or f.get("status") != "active":
            continue
        if not (f.get("valid_from") <= now and (f.get("valid_to") is None or now < f.get("valid_to"))):
            continue
        if f.get("condition_family") not in (None, p["family"]):
            continue
        sources: list[tuple[Node | None, Node | None]] = [(m, i) for _, m in g.out(f, "LEARNED_FROM") if "Message" in m.labels
                   for _, s in g.out(m, "IN") for _, i in g.out(s, "CONCERNS")]
        for m, i in sources or [(None, None)]:
            rows.append({"id": f.get("id"), "predicate": f.get("predicate"),
                         "value": f.get("object"), "condition_family": f.get("condition_family"),
                         "source": f.get("source"), "recorded_at": f.get("recorded_at"),
                         "said": m.get("text") if m else None,
                         "learned_in": i.get("id") if i else None})
    return rows


@implements("chat/queries/recent_messages.cypher")
def _recent_messages(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    person = g.one("Person", key=p["person_key"])
    rows = []
    for _, s in (g.into(person, "WITH") if person else []):
        for _, i in g.out(s, "CONCERNS"):
            for _, m in g.into(s, "IN"):
                rows.append((m.get("at"), m.get("seq"), {"incident": i.get("id"),
                             "role": m.get("role"), "text": m.get("text"), "at": m.get("at")}))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [r for _, _, r in rows[:p["limit"]]]


# ===================================================================== tools/

@implements("tools/queries/upstream_candidates.cypher")
def _upstream_candidates(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    hits: dict[int, set[str]] = {}
    hops: dict[int, int] = {}
    for a in _alerting(g, p["alerting"]):
        for path in g.paths(a, "DEPENDS_ON", 1, 3):
            c = path[-1]
            hits.setdefault(c.id, set()).add(a.get("name"))
            hops[c.id] = min(hops.get(c.id, 99), len(path) - 1)
    rows = [{"name": g.nodes[c].get("name"), "label": sorted(g.nodes[c].labels)[0],
             "kind": g.nodes[c].get("kind"), "hits": len(hits[c]), "hops": hops[c]}
            for c in hits]
    return sorted(rows, key=lambda r: (-r["hits"], r["hops"], r["name"]))


@implements("tools/queries/blast_radius.cypher")
def _blast_radius(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    root = g.entity(p["node"])
    best: dict[int, int] = {}
    for up in (g.find("Service") if root else []):
        for path in g.paths(up, "DEPENDS_ON", 1, 4):
            if root is not None and path[-1].id == root.id:
                best[up.id] = min(best.get(up.id, 99), len(path) - 1)
    rows = [{"service": g.nodes[u].get("name"), "hops": h,
             "customer_facing": g.nodes[u].get("customer_facing")} for u, h in best.items()]
    return sorted(rows, key=lambda r: (r["hops"], r["service"]))


def _holds(e: Edge, at: int) -> bool:
    """valid_from <= at < valid_to, where a missing valid_to means open-ended."""
    valid_to = e.props.get("valid_to")
    return int(e.props.get("valid_from", at + 1)) <= at and (valid_to is None or at < valid_to)


@implements("tools/queries/who_to_page.cypher")
def _who_to_page(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    n, at, rows = g.entity(p["node"]), p["at"], []
    for o, team in (g.out(n, "OWNED_BY") if n else []):
        if "Team" not in team.labels or not _holds(o, at):
            continue
        on_call: list[Node | None] = [person for oc, person in g.into(team, "ON_CALL")
                   if "Person" in person.labels and _holds(oc, at)]
        for person in on_call or [None]:
            rows.append({"team": team.get("name"), "channel": team.get("channel"),
                         "on_call": person.get("handle") if person else None,
                         "on_call_name": person.get("name") if person else None})
    return rows


# ============================================================ seed (inline)

@inline(r"CREATE \(:Service \{key: \$k, name: \$n, tier: \$t, customer_facing: \$cf\}\)")
def _seed_service(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    g.create(["Service"], {"key": p["k"], "name": p["n"], "tier": p["t"],
                           "customer_facing": p["cf"]})
    return []


@inline(r"CREATE \(:Datastore \{key: \$k, name: \$n, kind: \$kind\}\)")
def _seed_datastore(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    g.create(["Datastore"], {"key": p["k"], "name": p["n"], "kind": p["kind"]})
    return []


@inline(r"MATCH \(x \{name: \$a\}\), \(y \{name: \$b\}\) .* CREATE \(x\)-\[:DEPENDS_ON\]->\(y\)")
def _seed_depends(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    x, y = g.entity(p["a"]), g.entity(p["b"])
    if x and y:
        g.edges.append(Edge(x.id, "DEPENDS_ON", y.id))
    return []


@inline(r"CREATE \(:Team \{key: \$k, name: \$n, channel: \$c\}\)")
def _seed_team(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    g.create(["Team"], {"key": p["k"], "name": p["n"], "channel": p["c"]})
    return []


@inline(r"MATCH \(x \{name: \$node\}\), \(t:Team \{name: \$team\}\) .* "
        r"CREATE \(x\)-\[:OWNED_BY \{valid_from: \$t0\}\]->\(t\)")
def _seed_owner(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    x, t = g.entity(p["node"]), g.one("Team", name=p["team"])
    if x and t:
        g.edges.append(Edge(x.id, "OWNED_BY", t.id, {"valid_from": p["t0"]}))
    return []


@inline(r"MATCH \(t:Team \{name: \$team\}\) CREATE \(p:Person \{key: \$k, handle: \$h, "
        r"name: \$n\}\)-\[:MEMBER_OF \{valid_from: \$t0\}\]->\(t\)")
def _seed_person(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Team", name=p["team"])
    if t:
        person = g.create(["Person"], {"key": p["k"], "handle": p["h"], "name": p["n"]})
        g.edges.append(Edge(person.id, "MEMBER_OF", t.id, {"valid_from": p["t0"]}))
    return []


@inline(r"MATCH \(p:Person \{handle: \$h\}\), \(t:Team \{name: \$team\}\) "
        r"CREATE \(p\)-\[:ON_CALL \{valid_from: \$t0\}\]->\(t\)")
def _seed_on_call(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    person, t = g.one("Person", handle=p["h"]), g.one("Team", name=p["team"])
    if person and t:
        g.edges.append(Edge(person.id, "ON_CALL", t.id, {"valid_from": p["t0"]}))
    return []


@inline(r"CREATE \(:Canary \{key: 'canary', value: \$v\}\)")
def _seed_canary(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    g.create(["Canary"], {"key": "canary", "value": p["v"]})
    return []


# ================================================ tests and scripts (inline)
# Short ad-hoc queries the test suites and scripts/acceptance.py use for checks.

def exact(cypher: str) -> Callable[[Impl], Impl]:
    return inline(re.escape(_norm(cypher)))


@exact("CREATE (:Incident {key: 'incident:t1', status: 'open'})")
def _t_incident(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    g.create(["Incident"], {"key": "incident:t1", "status": "open"})
    return []


@exact("MATCH (t:Task {id: $id}) SET t.lease_until = timestamp() - 1")
def _t_expire(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    for t in g.find("Task", id=p["id"]):
        g.set(t, {"lease_until": g.clock_ms - 1})
    return []


def _count_query(g: GraphDouble, cypher: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    label = re.match(r"MATCH \(n:(\w+)\)", cypher).group(1)  # type: ignore[union-attr]
    return [{"count(n)": len(g.find(label, **p))}]


def _playbooks_from(g: GraphDouble, key: str) -> list[Node]:
    i = g.one("Incident", key=key)
    return [pb for _, pb in (g.into(i, "LEARNED_FROM") if i else []) if "Playbook" in pb.labels]


@exact("MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) RETURN p.id")
def _t_playbook_ids(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"p.id": pb.get("id")} for pb in _playbooks_from(g, p["k"])]


@exact("MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) "
       "RETURN p.id, p.signature")
def _t_playbook_sigs(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"p.id": pb.get("id"), "p.signature": pb.get("signature")}
            for pb in _playbooks_from(g, p["k"])]


@exact("MATCH (p:Memory:Playbook)-[:LEARNED_FROM]->(:Incident {key: $k}) "
       "MATCH (p)-[:ABOUT]->(n) RETURN p.signature, n.name")
def _t_playbook_about(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"p.signature": pb.get("signature"), "n.name": n.get("name")}
            for pb in _playbooks_from(g, p["k"]) for _, n in g.out(pb, "ABOUT")]


@exact("MATCH (f:Memory:Fact)-[:LEARNED_FROM]->(:Message)-[:IN]->(:Session)"
       "-[:CONCERNS]->(:Incident {key: $k}) RETURN f.predicate, f.object")
def _t_prefs_from(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for f in g.find("Fact"):
        for _, m in g.out(f, "LEARNED_FROM"):
            for _, s in g.out(m, "IN"):
                for _, i in g.out(s, "CONCERNS"):
                    if i.get("key") == p["k"]:
                        rows.append({"f.predicate": f.get("predicate"), "f.object": f.get("object")})
    return rows


@exact("MATCH (f:Memory:Fact)-[:ABOUT]->(:Person {key: 'person:priya'}) "
       "RETURN f.predicate, f.object, f.condition_family, f.source")
def _t_priya_facts(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    priya = g.one("Person", key="person:priya")
    return [{"f.predicate": f.get("predicate"), "f.object": f.get("object"),
             "f.condition_family": f.get("condition_family"), "f.source": f.get("source")}
            for _, f in (g.into(priya, "ABOUT") if priya else []) if "Fact" in f.labels]


@exact("MATCH (p:Memory:Playbook {signature: $s}) RETURN p.helped, p.misled, p.trust, p.status")
def _t_playbook_trust(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"p.helped": pb.get("helped"), "p.misled": pb.get("misled"),
             "p.trust": pb.get("trust"), "p.status": pb.get("status")}
            for pb in g.find("Playbook", signature=p["s"])]


@exact("MATCH (m:Message {role: 'engineer'})-[:IN]->(:Session)-[:CONCERNS]->"
       "(:Incident {key: $k}) RETURN m.text")
def _t_engineer_said(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"m.text": m.get("text")} for m in g.find("Message", role="engineer")
            for _, s in g.out(m, "IN") for _, i in g.out(s, "CONCERNS")
            if i.get("key") == p["k"]]


@exact("MATCH (:Incident {key: $k})<-[:FOR]-(:Decision)-[u:USED]->(m:Memory:Playbook) "
       "WHERE u.applied RETURN m.id, u.target")
def _t_applied(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    i = g.one("Incident", key=p["k"])
    return [{"m.id": m.get("id"), "u.target": e.props.get("target")}
            for _, d in (g.into(i, "FOR") if i else []) if "Decision" in d.labels
            for e, m in _usage(g, d) if "Playbook" in m.labels and e.props.get("applied")]


@exact("MATCH (a:Alert)-[:PART_OF]->(i:Incident) WHERE i.key IN [$a, $b] "
       "RETURN i.key, collect(DISTINCT a.text)")
def _t_wording(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key in dict.fromkeys([p["a"], p["b"]]):
        i = g.one("Incident", key=key)
        texts = list(dict.fromkeys(a.get("text") for _, a in (g.into(i, "PART_OF") if i else [])))
        if texts:
            rows.append({"i.key": key, "collect(DISTINCT a.text)": texts})
    return rows


@exact("MATCH (:Task {id: $t})-[:HAS_CHECKPOINT]->(c) RETURN count(c)")
def _t_checkpoint_count(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Task", id=p["t"])
    return [{"count(c)": len(g.out(t, "HAS_CHECKPOINT")) if t else 0}]


@exact("MATCH (:Task {id: $t})-[:HAS_CHECKPOINT]->(c) RETURN c.n, c.epoch ORDER BY c.n")
def _t_checkpoint_epochs(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    t = g.one("Task", id=p["t"])
    cs = sorted((c for _, c in (g.out(t, "HAS_CHECKPOINT") if t else [])), key=lambda c: c.get("n"))
    return [{"c.n": c.get("n"), "c.epoch": c.get("epoch")} for c in cs]


@exact("MATCH (t:Task {id: $t}) RETURN t.status, t.epoch")
def _t_task_state(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"t.status": t.get("status"), "t.epoch": t.get("epoch")}
            for t in g.find("Task", id=p["t"])]


def _actions(g: GraphDouble, key: str) -> list[Node]:
    _, ts = _incident_tasks(g, key)
    return list({a.id: a for t in ts for _, a in g.out(t, "EMITTED")}.values())


@exact("MATCH (:Incident {key: $k})<-[:FOR]-(:Task)-[:EMITTED]->(a:Action) "
       "RETURN a.channel, a.payload")
def _t_actions(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"a.channel": a.get("channel"), "a.payload": a.get("payload")}
            for a in _actions(g, p["k"])]


@exact("MATCH (:Incident {key: $k})<-[:FOR]-(:Task)-[:EMITTED]->(a:Action) "
       "RETURN a.recipient, a.channel, a.payload")
def _t_actions_to(g: GraphDouble, p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"a.recipient": a.get("recipient"), "a.channel": a.get("channel"),
             "a.payload": a.get("payload")} for a in _actions(g, p["k"])]


__all__ = ["ContractError", "GraphDouble", "query_params", "return_columns"]
