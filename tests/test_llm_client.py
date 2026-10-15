"""The OpenAI-compatible client against a local fake endpoint: retries, spacing, cache."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

from common.llm import LLMError, OpenAICompatible

OK = {"choices": [{"message": {"content": "", "tool_calls": [
    {"function": {"name": "inspect_metrics", "arguments": "{\"node\": \"postgres-orders\"}"}}]}}]}


class Fake(BaseHTTPRequestHandler):
    """Answers with the queued status codes, then 200 with OK."""

    queue: ClassVar[list[int]] = []
    hits: ClassVar[int] = 0

    def do_POST(self) -> None:
        type(self).hits += 1
        self.rfile.read(int(self.headers["Content-Length"]))
        status = self.queue.pop(0) if self.queue else 200
        self.send_response(status)
        if status in (429, 503):
            self.send_header("Retry-After", "0")
        self.end_headers()
        if status == 200:
            self.wfile.write(json.dumps(OK).encode())

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


if __name__ == "__main__":
    unittest.main()
