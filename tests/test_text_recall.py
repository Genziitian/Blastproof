"""Arm B building blocks: deterministic embeddings and incremental indexing."""
from __future__ import annotations

import math
import unittest

from eval import truth
from memory.embed import HashEmbedder, tokens
from memory.text_recall import index_playbooks
from scripts.run_incident import run_incident
from scripts.seed import seed_graph
from tests.backends import double


class EmbedTests(unittest.TestCase):
    def test_tokens_keep_names_their_parts_and_pairs(self):
        toks = tokens("postgres-orders: p95 latency")
        self.assertIn("postgres-orders", toks)
        self.assertIn("orders", toks)
        self.assertIn("p95_latency", toks)

    def test_hash_embeddings_are_deterministic_and_normalised(self):
        e = HashEmbedder(64)
        [a], [b] = e.embed(["checkout-api latency alarm"]), e.embed(["checkout-api latency alarm"])
        self.assertEqual(a, b)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in a)), 1.0, places=4)
        self.assertEqual(len(a), 64)


class IndexTests(unittest.TestCase):
    def test_only_new_or_changed_playbooks_are_embedded(self):
        g = double("text_index")
        seed_graph(g, "a")
        run_incident(g, truth.load("s01"), "s01-t", chat_model=None)
        e = HashEmbedder()
        self.assertEqual(index_playbooks(g, e), 1)
        self.assertEqual(index_playbooks(g, e), 0)


if __name__ == "__main__":
    unittest.main()
