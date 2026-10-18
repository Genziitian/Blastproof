"""Run the benchmark: each arm replays the 30 incidents in time order in its own graph.

    python -m eval.run --arms A C                 # the configured model (.env)
    python -m eval.run --arms A C --rule-based    # no model: deterministic planner
    python -m eval.run --arms C --only e01 e07    # a subset, for a quick check

Arms differ ONLY in memory access (plan, Evaluation):
  A  no recall: the investigator always investigates from scratch
  B  text retrieval: nearest memories by embedding similarity (FalkorDB vector index)
  C  graph retrieval: proximity in the dependency graph (A1/A1b)
B and C share the same records, validity and trust rules, precondition executor,
feedback and learning.

M2 (recall@5) is measured inside arm C before each incident: both retrievers query
the same frozen snapshot, so what each arm learned earlier can't skew it.

Every arm uses the same planner, model, tools, world and oracle. Conversation memory
(the war room) is on in every arm, so the responder behaves the same; only the
investigator's recall differs. Results go to eval/results/<name>/: one row per
incident (rows.jsonl), the aggregates (summary.json) and a readable table
(summary.md). Timings only mean something from a run with LLM_CACHE_DIR unset.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from agents import investigator
from agents.llm_planner import GuardedLLMPlanner
from agents.planning import Planner, RuleBasedPlanner
from common import config, llm, logs
from common.db import raw_graph, run
from eval import scenarios, truth
from memory import embed, recall, text_recall
from scripts.run_incident import run_incident
from scripts.seed import seed_graph
from sim import org
from sim import world as W
from sim.families import Evidence

RESULTS = Path(__file__).resolve().parent / "results"
ARMS = {"A": "no memory", "B": "text memory", "C": "graph memory"}
MODEL_STATS = ("calls", "retries", "errors", "cache_hits", "input_tokens", "output_tokens",
               "prompt_cache_read_tokens", "prompt_cache_write_tokens")

GraphFactory = Callable[[str], Any]


def live_graph(name: str) -> Any:
    """A fresh FalkorDB graph for one arm (deleted first)."""
    g = raw_graph(name)
    with contextlib.suppress(Exception):
        g.delete()
    return raw_graph(name)


class Arm:
    def __init__(self, name: str, make_graph: GraphFactory, model: Any, suffix: str = "") -> None:
        self.name = name
        self.model = model
        self.planner: Planner = GuardedLLMPlanner(model) if model else RuleBasedPlanner()
        self.graph = make_graph(f"eval_{name.lower()}{suffix}")
        seed_graph(self.graph, "a")
        self.applied_events: set[tuple[int, str, str]] = set()
        self.embedder = embed.from_config()
        self.measure_recall = name == "C" and not suffix

    @property
    def use_memory(self) -> bool:
        return self.name != "A"

    def _counters(self) -> dict[str, int]:
        stats = dict(getattr(self.model, "stats", {}) or {})
        return {k: int(stats.get(k, 0)) for k in MODEL_STATS} | {
            "fallbacks": int(getattr(self.planner, "fallbacks", 0))}

    def _apply_org(self, t: truth.Truth) -> None:
        for e in t.org_events:
            key = (e.at_ms, e.kind, e.person or e.node or "")
            if key in self.applied_events or e.at_ms > t.onset_ms:
                continue
            if e.kind == "on_call" and e.person:
                org.hand_over_on_call(self.graph, e.team, e.person, e.at_ms)
            elif e.kind == "owner" and e.node:
                org.move_ownership(self.graph, e.node, e.team, e.at_ms)
            self.applied_events.add(key)

    def incident(self, t: truth.Truth) -> dict[str, Any]:
        self._apply_org(t)
        m2 = recall_at_5(self.graph, self.embedder, t) if self.measure_recall else None
        before = self._counters()
        started = time.perf_counter()
        key = run_incident(self.graph, t, f"{t.id}-{self.name.lower()}",
                           use_memory=self.use_memory, planner=self.planner,
                           instance=f"eval-{self.name.lower()}", chat_model=self.model,
                           recall_mode="text" if self.name == "B" else "graph",
                           embedder=self.embedder)
        seconds = time.perf_counter() - started
        delta = {k: v - before[k] for k, v in self._counters().items()}
        row = score(self.name, t, self.graph, key, seconds, delta)
        row["m2"] = m2
        return row


def recall_at_5(g: Any, embedder: Any, t: truth.Truth) -> dict[str, Any]:
    """Before an incident, ask both retrievers for their top 5 on the same snapshot.

    A (memory, target) pair is relevant when the memory's failure family is the
    incident's and the target is its root, i.e. following it gives the right answer.
    """
    sc = t.scenario()
    alerts = Evidence(sc).alerts()
    alerting = sorted({a["service"] for a in alerts})
    texts = [a["text"] for a in alerts]
    kind = W.DATASTORES.get(t.root, "service")
    books = run(g, "memory/queries/playbook_texts.cypher", {})
    families = {b["id"]: b["family"] for b in books}
    exists = any(b["family"] == t.family and (t.root in (b["about"] or [])
                                              or (kind != "service" and b["kind"] == kind))
                 for b in books)

    def rank(found: Sequence[recall.Recalled]) -> int | None:
        """1-based position of the first pair that gives the right answer."""
        return next((i for i, r in enumerate(found, 1)
                     if families.get(r.memory_id) == t.family and r.target == t.root), None)

    graph_top = recall.recall(g, alerting, sc.now_ms)
    text_top = text_recall.recall(g, embedder, alerting, texts, sc.now_ms)
    graph_rank, text_rank = rank(graph_top), rank(text_top)
    return {"relevant_exists": exists, "graph_hit": graph_rank is not None,
            "text_hit": text_rank is not None, "graph_rank": graph_rank, "text_rank": text_rank,
            "graph_candidates": len(graph_top), "text_candidates": len(text_top),
            "active_playbooks": len(books)}


def score(arm: str, t: truth.Truth, g: Any, key: str, seconds: float,
          delta: dict[str, int]) -> dict[str, Any]:
    outcome = run(g, "agents/queries/incident_outcome.cypher", {"incident_key": key})[0]
    tasks = run(g, "agents/queries/incident_report.cypher", {"incident_key": key})
    usage = run(g, "eval/queries/incident_usage.cypher", {"incident_key": key})
    actions = run(g, "eval/queries/incident_actions.cypher", {"incident_key": key})
    steps = sum(r["checkpoints"] for r in tasks if r["type"] == "investigate")
    first = actions[0] if actions else {"recipient": None, "channel": None}
    applied = [u for u in usage if u["applied"]]
    return {
        "arm": arm, "id": t.id, "category": t.category, "family": t.family, "root": t.root,
        "diagnosis_root": outcome["root"], "diagnosis_family": outcome["family"],
        "correct": outcome["root"] == t.root and outcome["family"] == t.family,
        "expected_recipient": t.expected_recipient, "recipient": first["recipient"],
        "recipient_ok": first["recipient"] == t.expected_recipient,
        "expected_channel": t.expected_channel, "channel": first["channel"],
        "channel_ok": first["channel"] == t.expected_channel,
        "notifications": len(actions),
        "steps": steps, "seconds": round(seconds, 3),
        "llm_requests": delta["calls"], **{k: delta[k] for k in MODEL_STATS if k != "calls"},
        "fallbacks": delta["fallbacks"],
        "memories_considered": len(usage),
        "memory_applied": bool(applied),
        "helped": any(u["verdict"] == "helped" for u in usage),
        "misled": any(u["verdict"] == "misled" for u in usage),
        "wrong_family_rejected": sum(1 for u in usage
                                     if not u["applied"] and u["family"] != t.family),
        "memories": usage,
    }


def run_m5(make_graph: GraphFactory, model: Any,
           on_row: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Seed a wrong playbook, replay three cache failures, watch it retire (arm C)."""
    arm = Arm("C", make_graph, model, suffix="_m5")
    seed_key = "incident:m5-seed"
    run(arm.graph, "agents/queries/open_incident.cypher", {
        "incident_key": seed_key, "incident_id": "m5-seed", "alerts": [],
        "observed_at": scenarios.START_MS - scenarios.HOUR})
    run(arm.graph, "memory/queries/write_playbook.cypher", {
        **scenarios.M5_PLAYBOOK.fields(), "id": scenarios.M5_PLAYBOOK_ID,
        "incident_key": seed_key, "root": scenarios.M5_PINNED_TO,
        "scenario_now": scenarios.START_MS - scenarios.HOUR})
    rows = []
    for sid in scenarios.m5_ids():
        row = arm.incident(truth.load(sid))
        state = run(arm.graph, "eval/queries/memory_state.cypher",
                    {"id": scenarios.M5_PLAYBOOK_ID})[0]
        row["wrong_playbook"] = state
        rows.append(row)
        if on_row:
            on_row(row)
    misled = [r for r in rows if any(u["memory"] == scenarios.M5_PLAYBOOK_ID
                                     and u["verdict"] == "misled" for u in r["memories"])]
    retired_after = next((i + 1 for i, r in enumerate(rows)
                          if r["wrong_playbook"]["status"] == "retired"), None)
    return {
        "rows": rows,
        "misleading_uses_before_retirement": len(misled),
        "retired_after_incident": retired_after,
        "correct_after_retirement": all(r["correct"] for r in rows[retired_after:])
        if retired_after else False,
    }


def _avg(rows: Sequence[dict[str, Any]], key: str) -> float | None:
    values = [r[key] for r in rows if r.get(key) is not None]
    return round(mean(values), 3) if values else None


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    measured = [r["m2"] for r in rows if r.get("m2") and r["m2"]["relevant_exists"]]
    if measured:
        out["m2"] = {"n": len(measured),
                     "graph_recall_at_5": round(sum(m["graph_hit"] for m in measured)
                                                / len(measured), 3),
                     "text_recall_at_5": round(sum(m["text_hit"] for m in measured)
                                               / len(measured), 3)}
        if all("graph_rank" in m for m in measured):  # runs from Oct 18 on record ranks
            for arm in ("graph", "text"):
                for k in (1, 3):
                    out["m2"][f"{arm}_recall_at_{k}"] = round(
                        sum((m[f"{arm}_rank"] or 99) <= k for m in measured) / len(measured), 3)
            out["m2"]["mean_candidates"] = round(mean(m["graph_candidates"] for m in measured), 2)
            out["m2"]["max_active_playbooks"] = max(m["active_playbooks"] for m in measured)
    for arm in sorted({r["arm"] for r in rows}):
        mine = [r for r in rows if r["arm"] == arm]
        cats: dict[str, Any] = {}
        for cat in ["all", *dict.fromkeys(r["category"] for r in mine)]:
            sel = mine if cat == "all" else [r for r in mine if r["category"] == cat]
            cats[cat] = {
                "n": len(sel),
                "accuracy": round(sum(r["correct"] for r in sel) / len(sel), 3),
                "recipient_ok": sum(r["recipient_ok"] for r in sel),
                "channel_ok": sum(r["channel_ok"] for r in sel),
                **{f"mean_{k}": _avg(sel, k) for k in
                   ("steps", "llm_requests", "input_tokens", "output_tokens",
                    "prompt_cache_read_tokens", "seconds")},
                "fallbacks": sum(r["fallbacks"] for r in sel),
                "errors": sum(r["errors"] for r in sel),
                "memory_helped": sum(r["helped"] for r in sel),
                "memory_misled": sum(r["misled"] for r in sel),
                "wrong_family_rejected": sum(r["wrong_family_rejected"] for r in sel),
                "duplicate_notifications": sum(max(0, r["notifications"] - 1) for r in sel),
            }
        out[arm] = cats
    return out


def markdown(summary: dict[str, Any], m5: dict[str, Any] | None, meta: dict[str, Any]) -> str:
    lines = [f"# Eval results: {meta['name']}", "",
             f"Model: `{meta['model']}` · text embeddings (arm B): "
             f"`{meta.get('embedder', 'n/a')}` · run at {meta['at']} · LLM disk cache: "
             f"{'on (timings not valid)' if meta['cached'] else 'off'}", ""]
    arms = sorted(a for a in summary if a in ARMS)
    cats = [c for c in summary[arms[0]] if c != "all"] + ["all"]
    lines += ["## Root-cause accuracy (M3)", "",
              "| Category | " + " | ".join(f"{a}: {ARMS.get(a, a)}" for a in arms) + " |",
              "|---|" + "---|" * len(arms)]
    for c in cats:
        cells = [f"{summary[a][c]['accuracy']:.0%} ({summary[a][c]['n']})" for a in arms]
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    lines += ["", "## Work per incident (M1), repeat and related incidents", "",
              "| Arm | steps | LLM requests | input tokens | output tokens | seconds |",
              "|---|---|---|---|---|---|"]
    for a in arms:
        for c in ("repeat", "related"):
            s = summary[a].get(c)
            if s:
                lines.append(f"| {a} {c} | {s['mean_steps']} | {s['mean_llm_requests']} | "
                             f"{s['mean_input_tokens']} | {s['mean_output_tokens']} | "
                             f"{s['mean_seconds']} |")
    lines += ["", "## Judgment (M4) and safety", "",
              "| Arm | same-symptom: wrong memory rejected / misled | novel: memory applied "
              "(misled) | org: right recipient | duplicate notifications | fallbacks |",
              "|---|---|---|---|---|---|"]
    for a in arms:
        s, all_ = summary[a], summary[a]["all"]
        same, novel, orgc = s.get("same", {}), s.get("novel", {}), s.get("org", {})
        lines.append(f"| {a} | {same.get('wrong_family_rejected', 0)} / "
                     f"{same.get('memory_misled', 0)} | {novel.get('memory_helped', 0)} "
                     f"({novel.get('memory_misled', 0)}) | "
                     f"{orgc.get('recipient_ok', 0)}/{orgc.get('n', 0)} | "
                     f"{all_['duplicate_notifications']} | {all_['fallbacks']} |")
    if "m2" in summary:
        m2 = summary["m2"]
        lines += ["", "## Retrieval (M2): recall@5 on the same snapshot", "",
                  f"Over the {m2['n']} incidents where a memory that gives the right answer "
                  f"already exists: graph retrieval finds it in its top 5 "
                  f"**{m2['graph_recall_at_5']:.0%}** of the time, text retrieval "
                  f"**{m2['text_recall_at_5']:.0%}**."]
        if "graph_recall_at_1" in m2:
            lines += ["", f"Ranked: graph recall@1 {m2['graph_recall_at_1']:.0%}, "
                          f"@3 {m2['graph_recall_at_3']:.0%}; text recall@1 "
                          f"{m2['text_recall_at_1']:.0%}, @3 {m2['text_recall_at_3']:.0%}. "
                          f"Mean candidates returned: {m2['mean_candidates']}; at most "
                          f"{m2['max_active_playbooks']} playbooks existed, so top-5 is a "
                          "small pool here."]
    if m5:
        lines += ["", "## M5: a deliberately wrong playbook", "",
                  f"Misleading uses before retirement: **{m5['misleading_uses_before_retirement']}** "
                  f"(retired after incident {m5['retired_after_incident']}); correct after "
                  f"retirement: {m5['correct_after_retirement']}."]
    lines += ["", "Results describe this synthetic 30-incident benchmark only."]
    return "\n".join(lines) + "\n"


def run_eval(arm_names: Sequence[str], make_graph: GraphFactory,
             model_factory: Callable[[], Any], only: Sequence[str] | None = None,
             with_m5: bool = True, log: Callable[[str], None] = print,
             on_row: Callable[[dict[str, Any]], None] | None = None,
             ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    """Replay the benchmark. `on_row` sees each incident's row as soon as it is scored,
    so a long run that dies part-way keeps everything it finished."""
    ids = [i for i in scenarios.ids() if not only or i in only]
    rows: list[dict[str, Any]] = []
    for name in arm_names:
        if name not in ARMS:
            raise SystemExit(f"arm {name!r} is not available yet (have {sorted(ARMS)})")
        arm = Arm(name, make_graph, model_factory())
        for sid in ids:
            row = arm.incident(truth.load(sid))
            rows.append(row)
            if on_row:
                on_row(row)
            log(f"{name} {sid} {row['category']:<8} {'ok ' if row['correct'] else 'BAD'} "
                f"steps={row['steps']} llm={row['llm_requests']} "
                f"{'helped' if row['helped'] else 'misled' if row['misled'] else ''}")
    m5 = run_m5(make_graph, model_factory(), on_row) if with_m5 and "C" in arm_names else None
    return rows, summarize(rows), m5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arms", nargs="+", default=["A", "B", "C"])
    ap.add_argument("--name", default=None, help="results folder (default: timestamp)")
    ap.add_argument("--only", nargs="*", help="run just these incident ids")
    ap.add_argument("--rule-based", action="store_true", help="ignore LLM_MODEL")
    ap.add_argument("--no-m5", action="store_true")
    ap.add_argument("--max-steps", type=int, default=None,
                    help="cap the investigator's step budget (default 12), e.g. to measure "
                         "accuracy when steps are scarce")
    args = ap.parse_args()
    logs.setup("WARNING")
    if args.max_steps:
        investigator.MAX_STEPS = args.max_steps

    def model_factory() -> Any:
        return None if args.rule_based else llm.from_config()

    model_name = "rule-based" if args.rule_based or not config.LLM_MODEL else config.LLM_MODEL
    problem = llm.check(model_factory())
    if problem:
        print(f"The model {model_name} did not answer a test request:\n  {problem}\n"
              "Not running: every step would fall back to the rule-based planner and the "
              "results would be labelled as a model run.\nFix LLM_API_KEY / LLM_MODEL in .env, "
              "or run `make eval-rules` for the deterministic benchmark.")
        return 2
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    name = args.name or f"{at}-{model_name.replace('/', '_')}"
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    partial = out / "rows.partial.jsonl"
    partial.write_text("", encoding="utf-8")

    def save(row: dict[str, Any]) -> None:
        with partial.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    print(f"saving each incident to {partial} as it finishes")
    rows, summary, m5 = run_eval(args.arms, live_graph, model_factory, args.only,
                                 not args.no_m5, on_row=save)
    meta = {"name": name, "model": model_name, "at": at, "arms": args.arms,
            "max_steps": investigator.MAX_STEPS,
            "embedder": embed.from_config().name,
            "cached": bool(config.LLM_CACHE_DIR) and not args.rule_based,
            "truth_ids": [r["id"] for r in rows]}
    if model_name != "rule-based" and not any(r.get("input_tokens") for r in rows):
        # The model never answered (every step fell back): not a model run.
        meta["invalid"] = "the model answered no request; every step used the rule-based planner"
        print(f"\nWARNING: {meta['invalid']}. Results are marked invalid and the Results tab "
              "ignores them.")
    (out / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    partial.unlink()
    (out / "summary.json").write_text(json.dumps(
        {"meta": meta, "summary": summary, "m5": m5}, indent=2, default=str), encoding="utf-8")
    (out / "summary.md").write_text(markdown(summary, m5, meta), encoding="utf-8")
    print(f"\n{markdown(summary, m5, meta)}\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

