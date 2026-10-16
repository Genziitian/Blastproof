"""Write docs/QUERIES.md: every Cypher query the product runs, with what it is for.

    python -m scripts.query_index          # rewrite docs/QUERIES.md
    python -m scripts.query_index --check  # exit 1 if docs/QUERIES.md is out of date

Each entry comes from the query file's own leading // comment, so the index can't
drift from the code (tests/test_boundaries.py runs --check).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "QUERIES.md"
GROUPS = [
    ("memory", "Memory: recall (A1, A1b), trust (A2), facts (A3), playbooks (A4)"),
    ("coord", "Coordination: fenced leases, checkpoints, actions, handoffs"),
    ("agents", "Agents: triage, decisions, confirmation"),
    ("chat", "Conversation memory: the war room"),
    ("tools", "Agent tools (also served over MCP): multi-hop graph questions"),
    ("sim", "Simulated world: deploy history and org changes"),
    ("web", "UI: what each panel reads"),
    ("eval", "Evaluator only"),
]


def summary(path: Path) -> str:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("//"):
            break
        lines.append(line.lstrip()[2:].strip())
    return " ".join(lines) or "(no description)"


def render() -> str:
    out = ["# Cypher queries", "",
           "Every query the product runs lives in a `.cypher` file; this index is generated from "
           "each file's leading comment (`python -m scripts.query_index`). Comment lines are "
           "stripped before a query is sent (`common/db.py`).", ""]
    total = 0
    for folder, title in GROUPS:
        files = sorted((ROOT / folder / "queries").glob("*.cypher"))
        if not files:
            continue
        out += [f"## {title}", "", "| Query | What it does |", "|---|---|"]
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            out.append(f"| [`{rel}`](../{rel}) | {summary(f).replace('|', '/')} |")
            total += 1
        out.append("")
    out.insert(4, f"{total} queries.\n")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = render()
    if args.check:
        ok = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("docs/QUERIES.md is up to date" if ok else "docs/QUERIES.md is out of date: "
              "run python -m scripts.query_index")
        return 0 if ok else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
