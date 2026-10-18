"""Timestamped, atomic benchmark artifacts consumed by the portal."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).resolve().parent / "results"


def save(kind: str, result: Any, name: str | None = None) -> Path:
    now = datetime.now(timezone.utc)
    name = name or f"{kind}-{now.strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.json"
    if Path(name).name != name or not name.startswith(kind) or not name.endswith(".json"):
        raise ValueError(f"result filename must start with {kind} and end with .json")
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({"meta": {"at": now.isoformat(), "kind": kind},
                                    "result": result}, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)
    return path
