"""Settings read from the environment, and from a `.env` file next to this package
(see .env.example). Real environment variables win over `.env`.

The company a worker serves comes ONLY from here or from a task envelope created
by trusted server code. No LLM-facing tool accepts a graph name as an argument.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def parse_env(text: str) -> dict[str, str]:
    """KEY=VALUE lines; blank lines, # comments and trailing ' # comments' ignored."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if value[:1] in ("'", '"') and value.count(value[0]) >= 2:
            value = value[1:value.index(value[0], 1)]
        elif value.startswith("#"):
            value = ""
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key.removeprefix("export ").strip()] = value
    return values


def load_env_file(path: Path = ENV_FILE) -> None:
    if path.is_file():
        for key, value in parse_env(path.read_text(encoding="utf-8")).items():
            os.environ.setdefault(key, value)


load_env_file()

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
FALKORDB_PASSWORD = os.getenv("FALKORDB_PASSWORD") or None

# Companies this deployment serves. Graph name = "company_<id>".
COMPANIES = [c.strip() for c in os.getenv("COMPANIES", "a,b").split(",") if c.strip()]

# Lease timing. Demo profile (6 s / 2 s) is disclosed on screen while recording.
TIMING_PROFILE = os.getenv("TIMING_PROFILE", "normal")
if TIMING_PROFILE == "demo":
    LEASE_TTL_MS, HEARTBEAT_MS = 6_000, 2_000
else:
    LEASE_TTL_MS, HEARTBEAT_MS = 30_000, 10_000

MAX_ATTEMPTS = 3

# Any OpenAI-compatible chat endpoint, or Anthropic's Messages API (chosen
# automatically when LLM_BASE_URL is api.anthropic.com, or set LLM_PROVIDER).
# Leave LLM_MODEL empty to run without a model: the rule-based planner and the
# rule-based preference parser take over.
#   Claude (with prompt caching):
#       LLM_BASE_URL=https://api.anthropic.com  LLM_MODEL=claude-haiku-5-5  LLM_API_KEY=...
#   Gemini (free tier, the project default; see .env.example):
#       LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
#       LLM_MODEL=gemini-3.5-flash  LLM_API_KEY=...  LLM_MIN_INTERVAL_S=6.5
#   Ollama (local, free):  LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=gemma4:e4b
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "60"))
LLM_MIN_INTERVAL_S = float(os.getenv("LLM_MIN_INTERVAL_S", "0"))   # 6.5 keeps under ~10 RPM
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))           # on 429 / 5xx
LLM_CACHE_DIR = os.getenv("LLM_CACHE_DIR", "")                     # empty = no cache
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")                       # anthropic | openai | auto
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))          # Anthropic: includes thinking
LLM_EFFORT = os.getenv("LLM_EFFORT", "")                           # Anthropic effort; empty = default


def graph_name(company_id: str) -> str:
    """Map a trusted company id to its graph. Rejects anything not configured."""
    if company_id not in COMPANIES:
        raise ValueError(f"unknown company {company_id!r}; configured: {COMPANIES}")
    return f"company_{company_id}"
