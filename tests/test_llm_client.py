"""The OpenAI-compatible client against a local fake endpoint: retries, spacing, cache."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

from common.llm import AnthropicMessages, LLMError, OpenAICompatible

OK = {"choices": [{"message": {"content": "", "tool_calls": [
    {"function": {"name": "inspect_metrics", "arguments": "{\"node\": \"postgres-orders\"}"}}]}}]}


CLAUDE = {
    "content": [
        {"type": "thinking", "thinking": "metrics first", "signature": "x"},
        {"type": "text", "text": "Checking the database."},
        {"type": "tool_use", "id": "t1", "name": "inspect_metrics",
         "input": {"node": "postgres-orders"}},
    ],
    "usage": {"input_tokens": 40, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 900, "output_tokens": 30},
}
TOOLS = [{"type": "function", "function": {
    "name": "inspect_metrics", "description": "Recent metrics",
    "parameters": {"type": "object", "properties": {"node": {"type": "string"}},
                   "required": ["node"]}}}]


class Fake(BaseHTTPRequestHandler):
    """Answers with the queued status codes, then 200 with OK."""

    queue: ClassVar[list[int]] = []
    hits: ClassVar[int] = 0
    last: ClassVar[dict] = {}

    def do_POST(self) -> None:
        type(self).hits += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).last = {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": body}
        status = self.queue.pop(0) if self.queue else 200
        self.send_response(status)
        if status in (429, 503, 529):
            self.send_header("Retry-After", "0")
        self.end_headers()
        if status == 200:
            reply = CLAUDE if self.path == "/v1/messages" else OK
            self.wfile.write(json.dumps(reply).encode())
        elif status == 404:
            self.wfile.write(b'{"error": {"message": "models/nope is not found"}}')

    def log_message(self, *args: object) -> None:
        pass


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        Fake.queue, Fake.hits = [], 0

    def client(self, **kw: object) -> OpenAICompatible:
        return OpenAICompatible(self.base, "m", **kw)  # type: ignore[arg-type]

    def test_rate_limit_is_retried(self) -> None:
        Fake.queue = [429, 503]
        c = self.client(max_retries=3)
        reply = c.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(reply.tool_calls[0].arguments, {"node": "postgres-orders"})
        self.assertEqual((c.stats["calls"], c.stats["retries"]), (3, 2))

    def test_gives_up_after_max_retries(self) -> None:
        Fake.queue = [429, 429, 429]
        with self.assertRaises(LLMError):
            self.client(max_retries=1).chat([{"role": "user", "content": "hi"}])
        self.assertEqual(Fake.hits, 2)

    def test_client_errors_are_not_retried(self) -> None:
        Fake.queue = [400]
        with self.assertRaises(LLMError):
            self.client(max_retries=3).chat([{"role": "user", "content": "hi"}])
        self.assertEqual(Fake.hits, 1)

    def test_error_message_includes_the_providers_explanation(self) -> None:
        Fake.queue = [404]
        with self.assertRaisesRegex(LLMError, "models/nope is not found"):
            self.client().chat([{"role": "user", "content": "hi"}])

    def test_requests_are_spaced_out(self) -> None:
        c = self.client(min_interval_s=0.2)
        start = time.monotonic()
        for _ in range(3):
            c.chat([{"role": "user", "content": "hi"}])
        self.assertGreaterEqual(time.monotonic() - start, 0.4)

    def test_cache_answers_repeats_without_a_request(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = self.client(cache_dir=d)
            first = c.chat([{"role": "user", "content": "hi"}])
            again = c.chat([{"role": "user", "content": "hi"}])
            other = c.chat([{"role": "user", "content": "different"}])
        self.assertEqual(first, again)
        self.assertEqual(other.tool_calls[0].name, "inspect_metrics")
        self.assertEqual((Fake.hits, c.stats["cache_hits"]), (2, 1))


class AnthropicClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        Fake.queue, Fake.hits, Fake.last = [], 0, {}
        self.client = AnthropicMessages(self.base, "claude-haiku-5-5", api_key="k")

    def ask(self, **kw: object):
        messages = [{"role": "system", "content": "You investigate."},
                    {"role": "user", "content": [{"type": "text", "text": "Alerting: cart-svc"},
                                                 {"type": "text", "text": "1. step"}]}]
        return self.client.chat(messages, **kw)  # type: ignore[arg-type]

    def test_request_uses_messages_api_with_prompt_caching(self) -> None:
        self.ask(tools=TOOLS)
        sent = Fake.last
        self.assertEqual(sent["path"], "/v1/messages")
        self.assertEqual(sent["headers"]["x-api-key"], "k")
        self.assertEqual(sent["headers"]["anthropic-version"], "2023-06-01")
        body = sent["body"]
        self.assertEqual(body["cache_control"], {"type": "ephemeral"})
        self.assertEqual(body["system"], [{"type": "text", "text": "You investigate."}])
        self.assertEqual([b["text"] for b in body["messages"][0]["content"]],
                         ["Alerting: cart-svc", "1. step"])
        self.assertEqual(body["tools"][0]["name"], "inspect_metrics")
        self.assertIn("input_schema", body["tools"][0])
        self.assertTrue(body["tool_choice"]["disable_parallel_tool_use"])
        self.assertNotIn("temperature", body)

    def test_reply_keeps_text_and_tool_use_and_skips_thinking(self) -> None:
        reply = self.ask(tools=TOOLS)
        self.assertEqual(reply.content, "Checking the database.")
        self.assertEqual([(c.name, c.arguments) for c in reply.tool_calls],
                         [("inspect_metrics", {"node": "postgres-orders"})])

    def test_usage_counts_prompt_cache_reads(self) -> None:
        self.ask(tools=TOOLS)
        s = self.client.stats
        self.assertEqual((s["input_tokens"], s["prompt_cache_read_tokens"], s["output_tokens"]),
                         (940, 900, 30))

    def test_overloaded_is_retried(self) -> None:
        Fake.queue = [529]
        self.ask()
        self.assertEqual(self.client.stats["retries"], 1)

    def test_openai_client_flattens_text_parts(self) -> None:
        OpenAICompatible(self.base, "m").chat(
            [{"role": "user", "content": [{"type": "text", "text": "a"},
                                          {"type": "text", "text": "b"}]}])
        self.assertEqual(Fake.last["body"]["messages"][0]["content"], "a\nb")



class CheckTests(unittest.TestCase):
    """llm.check: a run must not silently become rule-based (e.g. a revoked key)."""

    def test_reports_a_model_that_does_not_answer(self):
        from common import llm

        class Revoked:
            def chat(self, *a, **kw):
                raise LLMError("HTTP 401 Unauthorized: invalid x-api-key")

        class Fine:
            def chat(self, *a, **kw):
                return llm.Reply("OK")

        self.assertIn("401", llm.check(Revoked()) or "")
        self.assertIsNone(llm.check(Fine()))
        self.assertIsNone(llm.check(None))


if __name__ == "__main__":
    unittest.main()
