"""The .env reader: python -m unittest tests.test_config -v"""
from __future__ import annotations

import unittest

from common.config import parse_env


class EnvFileTests(unittest.TestCase):
    def test_values_comments_and_quotes(self):
        text = "\n".join([
            "# a comment",
            "",
            "LLM_MODEL=gemini-2.5-flash",
            "LLM_CACHE_DIR=            # e.g. .llm-cache",
            "LLM_MIN_INTERVAL_S=6.5 # spacing",
            'LLM_API_KEY="abc#123"',
            "export TIMING_PROFILE=demo",
            "URL=http://x/#frag",
        ])
        self.assertEqual(parse_env(text), {
            "LLM_MODEL": "gemini-2.5-flash", "LLM_CACHE_DIR": "", "LLM_MIN_INTERVAL_S": "6.5",
            "LLM_API_KEY": "abc#123", "TIMING_PROFILE": "demo", "URL": "http://x/#frag",
        })

    def test_example_file_parses(self):
        from pathlib import Path
        values = parse_env((Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8"))
        self.assertEqual(values["LLM_MODEL"], "")
        self.assertEqual(values["LLM_CACHE_DIR"], "")
        self.assertTrue(values["LLM_BASE_URL"].startswith("https://generativelanguage"))


if __name__ == "__main__":
    unittest.main()
