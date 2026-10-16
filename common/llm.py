"""Minimal LLM clients: any OpenAI-compatible endpoint, and Anthropic's Messages API.

Standard library only, so the project has no model-vendor dependency. Every caller
must cope with `LLMError` and fall back to deterministic logic: the model helps,
it is never load-bearing.

Both clients share one HTTP core that spaces requests out (LLM_MIN_INTERVAL_S),
retries 429 / 5xx / 529 answers with backoff (LLM_MAX_RETRIES, honouring
Retry-After), and can cache whole answers on disk (LLM_CACHE_DIR) for quick eval
reruns. `stats` counts calls, retries, errors, disk-cache hits and tokens, so
cached runs never pass for real latency.

The Anthropic client uses prompt caching: tools and the system prompt never change
between the investigator's turns, and each turn only appends one step, so a single
top-level `cache_control` lets every call reuse the previous call's prefix.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from common import config

RETRYABLE = {429, 500, 502, 503, 504, 529}
ANTHROPIC_VERSION = "2023-06-01"


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


def text_of(content: Any) -> str:
    """A message's text, whether it is a string or a list of text parts."""
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content or [])


class _HTTPModel:
    """Throttle, retries, disk cache and statistics shared by every provider."""

    def __init__(self, url: str, model: str, api_key: str = "", timeout_s: float = 60.0,
                 min_interval_s: float = 0.0, max_retries: int = 4,
                 cache_dir: str | None = None) -> None:
        self.url = url
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.stats: dict[str, int] = {
            "calls": 0, "cache_hits": 0, "retries": 0, "errors": 0,
            "input_tokens": 0, "output_tokens": 0,
            "prompt_cache_read_tokens": 0, "prompt_cache_write_tokens": 0,
        }
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _count_usage(self, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(body, sort_keys=True).encode()
        cached = self._cache_path(raw)
        if cached is not None and cached.exists():
            self.stats["cache_hits"] += 1
            data: dict[str, Any] = json.loads(cached.read_text(encoding="utf-8"))
            return data
        data = self._post(raw)
        self._count_usage(data)
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _post(self, raw: bytes) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", **self._headers()}
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
                    raise LLMError(f"{self.url}: HTTP {e.code} {e.reason}: {_body(e)}") from e
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


class OpenAICompatible(_HTTPModel):
    """Gemini, DeepSeek, Groq, OpenAI, Ollama: anything serving /chat/completions."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout_s: float = 60.0,
                 min_interval_s: float = 0.0, max_retries: int = 4,
                 cache_dir: str | None = None) -> None:
        super().__init__(f"{base_url}/chat/completions", model, api_key, timeout_s,
                         min_interval_s, max_retries, cache_dir)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _count_usage(self, data: dict[str, Any]) -> None:
        usage = data.get("usage") or {}
        self.stats["input_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.stats["output_tokens"] += int(usage.get("completion_tokens") or 0)

    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None, json_mode: bool = False) -> Reply:
        flat = [{"role": m["role"], "content": text_of(m["content"])} for m in messages]
        body: dict[str, Any] = {"model": self.model, "messages": flat, "temperature": 0}
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return _parse_openai(self._request(body))


class AnthropicMessages(_HTTPModel):
    """Claude through the native Messages API, with automatic prompt caching."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout_s: float = 60.0,
                 min_interval_s: float = 0.0, max_retries: int = 4,
                 cache_dir: str | None = None, max_tokens: int = 4096,
                 effort: str = "") -> None:
        root = base_url.rstrip("/").removesuffix("/v1")
        super().__init__(f"{root}/v1/messages", model, api_key, timeout_s,
                         min_interval_s, max_retries, cache_dir)
        self.max_tokens = max_tokens
        self.effort = effort

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION}

    def _count_usage(self, data: dict[str, Any]) -> None:
        usage = data.get("usage") or {}
        read = int(usage.get("cache_read_input_tokens") or 0)
        write = int(usage.get("cache_creation_input_tokens") or 0)
        self.stats["input_tokens"] += int(usage.get("input_tokens") or 0) + read + write
        self.stats["output_tokens"] += int(usage.get("output_tokens") or 0)
        self.stats["prompt_cache_read_tokens"] += read
        self.stats["prompt_cache_write_tokens"] += write

    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None, json_mode: bool = False) -> Reply:
        system = "\n\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")
        if json_mode:
            system += "\n\nReply with one JSON object only: no prose, no code fences."
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # One automatic breakpoint: tools + system + every earlier step are reused.
            "cache_control": {"type": "ephemeral"},
            "messages": [{"role": m["role"], "content": _blocks(m["content"])}
                         for m in messages if m["role"] != "system"],
        }
        if system:
            body["system"] = [{"type": "text", "text": system}]
        if tools:
            body["tools"] = [_anthropic_tool(t) for t in tools]
            body["tool_choice"] = {"type": "auto", "disable_parallel_tool_use": True}
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        reply = _parse_anthropic(self._request(body))
        if json_mode:
            return Reply(_json_only(reply.content), reply.tool_calls)
        return reply


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [{"type": "text", "text": part.get("text", "")} for part in content]


def _anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function", tool)
    return {"name": fn["name"], "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or fn.get("input_schema")
            or {"type": "object", "properties": {}}}


def _json_only(text: str) -> str:
    """The first JSON object in a reply, without code fences around it."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _body(error: urllib.error.HTTPError) -> str:
    """The provider's own explanation (e.g. which model name it did not find)."""
    try:
        return error.read().decode("utf-8", "replace").strip().replace("\n", " ")[:300]
    except Exception:
        return ""


def _backoff_s(error: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else None
    try:
        return min(60.0, float(retry_after)) if retry_after else min(60.0, 2.0 * 2 ** attempt)
    except ValueError:
        return min(60.0, 2.0 * 2 ** attempt)


def _parse_openai(data: dict[str, Any]) -> Reply:
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


def _parse_anthropic(data: dict[str, Any]) -> Reply:
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise LLMError(f"unexpected response shape: {str(data)[:200]}")
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    calls = [ToolCall(b.get("name", ""), dict(b.get("input") or {}))
             for b in blocks if b.get("type") == "tool_use"]
    return Reply(text, calls)


def check(model: ChatModel | None) -> str | None:
    """One tiny request before a run. None if the model answers, else the error.

    Planners fall back to rule-based steps on any model error, which is right
    mid-run but would silently turn a whole eval or demo into a rule-based one
    (for example with a revoked API key). Callers use this to stop or say so."""
    if model is None:
        return None
    try:
        model.chat([{"role": "user", "content": "Reply with the single word OK."}])
    except LLMError as e:
        return str(e)
    return None


def provider() -> str:
    """'anthropic' or 'openai' (the OpenAI-compatible wire format)."""
    if config.LLM_PROVIDER:
        return config.LLM_PROVIDER
    return "anthropic" if "anthropic.com" in config.LLM_BASE_URL else "openai"


def from_config() -> ChatModel | None:
    """The configured model, or None when LLM_MODEL is unset."""
    if not config.LLM_MODEL:
        return None
    common = (config.LLM_BASE_URL, config.LLM_MODEL, config.LLM_API_KEY, config.LLM_TIMEOUT_S,
              config.LLM_MIN_INTERVAL_S, config.LLM_MAX_RETRIES, config.LLM_CACHE_DIR or None)
    if provider() == "anthropic":
        return AnthropicMessages(*common, max_tokens=config.LLM_MAX_TOKENS,
                                 effort=config.LLM_EFFORT)
    return OpenAICompatible(*common)
