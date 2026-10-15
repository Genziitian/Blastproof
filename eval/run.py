"""Run the benchmark: each arm replays the 30 incidents in time order in its own graph.

    python -m eval.run --arms A C                 # the configured model (.env)
    python -m eval.run --arms A C --rule-based    # no model: deterministic planner
    python -m eval.run --arms C --only e01 e07    # a subset, for a quick check

Arms differ ONLY in memory access (plan, Evaluation):
  A  no recall: the investigator always investigates from scratch
  C  graph recall (A1/A1b), precondition checks, verdicts and learning
  B  text retrieval over the same records: added on Saturday

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

from agents.llm_planner import GuardedLLMPlanner
from agents.planning import Planner, RuleBasedPlanner
from common import config, llm, logs
from common.db import raw_graph, run
from eval import scenarios, truth
from scripts.run_incident import run_incident
from scripts.seed import seed_graph
from sim import org

RESULTS = Path(__file__).resolve().parent / "results"
ARMS = {"A": "no memory", "C": "graph memory"}
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
        before = self._counters()
        started = time.perf_counter()
        key = run_incident(self.graph, t, f"{t.id}-{self.name.lower()}",
                           use_memory=self.use_memory, planner=self.planner,
                           instance=f"eval-{self.name.lower()}", chat_model=self.model)
        seconds = time.perf_counter() - started
        delta = {k: v - before[k] for k, v in self._counters().items()}
        return score(self.name, t, self.graph, key, seconds, delta)


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


def run_m5(make_graph: GraphFactory, model: Any) -> dict[str, Any]:
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
             f"Model: `{meta['model']}` · run at {meta['at']} · LLM disk cache: "
             f"{'on (timings not valid)' if meta['cached'] else 'off'}", ""]
    arms = sorted(summary)
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
              "| Arm | same-symptom: wrong memory rejected / misled | novel: memory applied | "
              "org: right recipient | duplicate notifications | fallbacks |",
              "|---|---|---|---|---|---|"]
    for a in arms:
        s, all_ = summary[a], summary[a]["all"]
        same, novel, orgc = s.get("same", {}), s.get("novel", {}), s.get("org", {})
        lines.append(f"| {a} | {same.get('wrong_family_rejected', 0)} / "
                     f"{same.get('memory_misled', 0)} | {novel.get('memory_helped', 0)} | "
                     f"{orgc.get('recipient_ok', 0)}/{orgc.get('n', 0)} | "
                     f"{all_['duplicate_notifications']} | {all_['fallbacks']} |")
    if m5:
        lines += ["", "## M5: a deliberately wrong playbook", "",
                  f"Misleading uses before retirement: **{m5['misleading_uses_before_retirement']}** "
                  f"(retired after incident {m5['retired_after_incident']}); correct after "
                  f"retirement: {m5['correct_after_retirement']}."]
    lines += ["", "Results describe this synthetic 30-incident benchmark only."]
    return "\n".join(lines) + "\n"


def run_eval(arm_names: Sequence[str], make_graph: GraphFactory,
             model_factory: Callable[[], Any], only: Sequence[str] | None = None,
             with_m5: bool = True, log: Callable[[str], None] = print
             ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    ids = [i for i in scenarios.ids() if not only or i in only]
    rows: list[dict[str, Any]] = []
    for name in arm_names:
        if name not in ARMS:
            raise SystemExit(f"arm {name!r} is not available yet (have {sorted(ARMS)})")
        arm = Arm(name, make_graph, model_factory())
        for sid in ids:
            row = arm.incident(truth.load(sid))
            rows.append(row)
            log(f"{name} {sid} {row['category']:<8} {'ok ' if row['correct'] else 'BAD'} "
                f"steps={row['steps']} llm={row['llm_requests']} "
                f"{'helped' if row['helped'] else 'misled' if row['misled'] else ''}")
    m5 = run_m5(make_graph, model_factory()) if with_m5 and "C" in arm_names else None
    return rows, summarize(rows), m5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arms", nargs="+", default=["A", "C"])
    ap.add_argument("--name", default=None, help="results folder (default: timestamp)")
    ap.add_argument("--only", nargs="*", help="run just these incident ids")
    ap.add_argument("--rule-based", action="store_true", help="ignore LLM_MODEL")
    ap.add_argument("--no-m5", action="store_true")
    args = ap.parse_args()
    logs.setup("WARNING")

    def model_factory() -> Any:
        return None if args.rule_based else llm.from_config()

    model_name = "rule-based" if args.rule_based or not config.LLM_MODEL else config.LLM_MODEL
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    name = args.name or f"{at}-{model_name.replace('/', '_')}"
    rows, summary, m5 = run_eval(args.arms, live_graph, model_factory, args.only,
                                 not args.no_m5)
    meta = {"name": name, "model": model_name, "at": at, "arms": args.arms,
            "cached": bool(config.LLM_CACHE_DIR) and not args.rule_based,
            "truth_ids": [r["id"] for r in rows]}
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(
        {"meta": meta, "summary": summary, "m5": m5}, indent=2, default=str), encoding="utf-8")
    (out / "summary.md").write_text(markdown(summary, m5, meta), encoding="utf-8")
    print(f"\n{markdown(summary, m5, meta)}\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

