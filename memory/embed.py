"""Text embeddings for arm B (text retrieval over the same memories).

Two embedders behind one interface:

- `HashEmbedder` (default): a deterministic hashed bag of words and word pairs,
  L2-normalised. No model, no network, so tests and offline runs are repeatable.
- `OpenAIEmbedder`: any OpenAI-compatible /embeddings endpoint (e.g. Gemini's
  `gemini-embedding-001`), with an on-disk cache; set EMBED_MODEL to use it.

Embeddings are index data derived from a memory's text; they never change what a
memory says.
"""
from __future__ import annotations

import hashlib
import http.client
import itertools
import json
import math
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

from common import config
from common.llm import LLMError

WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def tokens(text: str) -> list[str]:
    """Words, the parts of hyphenated names, and adjacent word pairs."""
    words = WORD.findall(text.lower())
    parts = [p for w in words if "-" in w for p in w.split("-")]
    pairs = [f"{a}_{b}" for a, b in itertools.pairwise(words)]
    return words + parts + pairs


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


class HashEmbedder:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim
        self.name = f"hash-{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vector = [0.0] * self.dim
            for tok in tokens(text):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                vector[h % self.dim] += 1.0 if (h >> 64) & 1 else -1.0
            out.append(_normalise(vector))
        return out


class OpenAIEmbedder:
    def __init__(self, base_url: str, model: str, api_key: str, dim: int,
                 cache_dir: str | None = None, timeout_s: float = 60.0) -> None:
        self.url = f"{base_url.rstrip('/')}/embeddings"
        self.model, self.api_key, self.dim = model, api_key, dim
        self.name = model
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.timeout_s = timeout_s
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        key = hashlib.sha256(f"{self.model}|{self.dim}|{text}".encode()).hexdigest()
        path = self.cache_dir / f"emb-{key}.json" if self.cache_dir else None
        if path is not None and path.exists():
            cached: list[float] = json.loads(path.read_text(encoding="utf-8"))
            return cached
        body = {"model": self.model, "input": text, "dimensions": self.dim}
        request = urllib.request.Request(self.url, json.dumps(body).encode(), {
            "Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                data: dict[str, Any] = json.load(response)
        except (OSError, http.client.HTTPException, ValueError) as e:  # incl. dropped connections
            raise LLMError(f"{self.url}: {e}") from e
        self.calls += 1
        vector = _normalise([float(v) for v in data["data"][0]["embedding"]][: self.dim])
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(vector), encoding="utf-8")
        return vector


def from_config() -> Embedder:
    if config.EMBED_MODEL:
        return OpenAIEmbedder(config.EMBED_BASE_URL, config.EMBED_MODEL, config.EMBED_API_KEY,
                              config.EMBED_DIM, config.LLM_CACHE_DIR or None)
    return HashEmbedder(config.EMBED_DIM)
