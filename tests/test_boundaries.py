"""Architecture rules the plan depends on, checked statically.

- Ground truth stays evaluator-only: nothing the agents run imports `eval`.
- Every Cypher file the code references exists.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_SIDE = ["agents", "tools", "coord", "memory", "chat", "common"]
ALLOWED = {"tools/mcp_server.py"}  # dev harness that starts a scenario by hand


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class BoundaryTests(unittest.TestCase):
    def test_agent_side_never_imports_eval(self):
        for pkg in AGENT_SIDE:
            for path in (ROOT / pkg).rglob("*.py"):
                rel = path.relative_to(ROOT).as_posix()
                if rel in ALLOWED:
                    continue
                with self.subTest(file=rel):
                    bad = {m for m in imported_modules(path) if m == "eval" or m.startswith("eval.")}
                    self.assertFalse(bad, f"{rel} imports {bad}")

    def test_product_never_imports_the_test_double(self):
        """Rule 3: the product runs on FalkorDB; the graph double is for tests only."""
        offenders = []
        for path in ROOT.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(("tests/", ".venv/", "venv/")) or "/site-packages/" in rel:
                continue
            if any(m == "tests" or m.startswith("tests.") for m in imported_modules(path)):
                offenders.append(rel)
        self.assertEqual(offenders, [])

    def test_query_index_is_current(self):
        from scripts import query_index
        self.assertEqual((ROOT / "docs" / "QUERIES.md").read_text(encoding="utf-8"),
                         query_index.render(), "run python -m scripts.query_index")

    def test_every_query_file_says_what_it_does(self):
        for path in ROOT.glob("*/queries/*.cypher"):
            with self.subTest(query=path.name):
                self.assertTrue(path.read_text(encoding="utf-8").startswith("//"))

    def test_referenced_queries_exist(self):
        pattern = re.compile(r'"((?:agents|coord|memory|tools)/queries/\w+\.cypher)"')
        for path in ROOT.rglob("*.py"):
            for ref in pattern.findall(path.read_text(encoding="utf-8")):
                with self.subTest(file=path.name, query=ref):
                    self.assertTrue((ROOT / ref).exists(), f"{ref} missing")

    def test_query_dirs_resolve(self):
        """Prefix constants like Q = "coord/queries/" combined with file names."""
        pairs = re.compile(r'Q \+ "([\w.]+\.cypher)"')
        for path in ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            prefix = re.search(r'^Q = "([\w/]+/)"', text, re.M)
            if not prefix:
                continue
            for name in pairs.findall(text):
                with self.subTest(file=path.name, query=name):
                    self.assertTrue((ROOT / prefix.group(1) / name).exists())


if __name__ == "__main__":
    unittest.main()
