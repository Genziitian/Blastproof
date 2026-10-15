"""Minimal client for any OpenAI-compatible chat endpoint (Ollama, Groq, Gemini, ...).

Standard library only, so the project has no model-vendor dependency. Every caller
must cope with `LLMError` and fall back to deterministic logic: the model helps,
it is never load-bearing.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from common import config


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
                 timeout_s: float = 60.0) -> None:
        self.url = f"{base_url}/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s

    def chat(self, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None, json_mode: bool = False) -> Reply:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.url, json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                data = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise LLMError(f"{self.url}: {e}") from e
        return _parse(data)


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
                            config.LLM_TIMEOUT_S)
