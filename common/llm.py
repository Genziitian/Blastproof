"""Minimal client for any OpenAI-compatible chat endpoint (Gemini, Groq, Ollama, ...).

Standard library only, so the project has no model-vendor dependency. Every caller
must cope with `LLMError` and fall back to deterministic logic: the model helps,
it is never load-bearing.

Free tiers rate-limit hard (Gemini: roughly 10 requests a minute), so the client
spaces requests out (LLM_MIN_INTERVAL_S), retries 429 and 5xx answers with backoff
(LLM_MAX_RETRIES, honouring Retry-After), and can cache answers on disk
(LLM_CACHE_DIR) for quick eval reruns. Cached answers never count toward latency:
`stats` reports calls, cache hits and retries separately.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from common import config

RETRYABLE = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None, json_mode: bool = False) -> Reply: ...


class OpenAICompatible:
    def __init__(self, base_url: str, model: str, api_key: str = "",
                 timeout_s: float = 60.0, min_interval_s: float = 0.0,
                 max_retries: int = 4, cache_dir: str | None = None) -> None:
        self.url = f"{base_url}/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.stats = {"calls": 0, "cache_hits": 0, "retries": 0, "errors": 0}
        self._lock = threading.Lock()
        self._last_request = 0.0

    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None, json_mode: bool = False) -> Reply:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        raw = json.dumps(body, sort_keys=True).encode()
        cached = self._cache_path(raw)
        if cached is not None and cached.exists():
            self.stats["cache_hits"] += 1
            return _parse(json.loads(cached.read_text(encoding="utf-8")))
        data = self._post(raw)
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(data), encoding="utf-8")
        return _parse(data)

    def _post(self, raw: bytes) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            self.stats["calls"] += 1
            request = urllib.request.Request(self.url, raw, headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    data: dict[str, Any] = json.load(response)
                    return data
            except urllib.error.HTTPError as e:
                if e.code not in RETRYABLE or attempt == self.max_retries:
                    self.stats["errors"] += 1
                    raise LLMError(f"{self.url}: HTTP {e.code} {e.reason}") from e
                self.stats["retries"] += 1
                time.sleep(_backoff_s(e, attempt))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                self.stats["errors"] += 1
                raise LLMError(f"{self.url}: {e}") from e
        raise LLMError(f"{self.url}: gave up after {self.max_retries} retries")

    def _wait_turn(self) -> None:
        """Keep at least min_interval_s between requests from this process."""
        with self._lock:
            wait = self._last_request + self.min_interval_s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _cache_path(self, raw: bytes) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(self.url.encode() + b"\n" + raw).hexdigest()
        return self.cache_dir / f"{key}.json"


def _backoff_s(error: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else None
    try:
        return min(60.0, float(retry_after)) if retry_after else min(60.0, 2.0 * 2 ** attempt)
    except ValueError:
        return min(60.0, 2.0 * 2 ** attempt)


def _parse(data: dict[str, Any]) -> Reply:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected response shape: {str(data)[:200]}") from e
    calls = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError as e:
            raise LLMError(f"tool call arguments are not JSON: {raw[:200]}") from e
        calls.append(ToolCall(fn.get("name", ""), args))
    return Reply(message.get("content") or "", calls)


def from_config() -> ChatModel | None:
    """The configured model, or None when LLM_MODEL is unset."""
    if not config.LLM_MODEL:
        return None
    return OpenAICompatible(config.LLM_BASE_URL, config.LLM_MODEL, config.LLM_API_KEY,
                            config.LLM_TIMEOUT_S, config.LLM_MIN_INTERVAL_S,
                            config.LLM_MAX_RETRIES, config.LLM_CACHE_DIR or None)
