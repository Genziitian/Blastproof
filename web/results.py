"""Select completed result artifacts by their recorded time, not their folder order."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _source(path: Path, meta: dict[str, Any]) -> dict[str, Any]:
    at = meta.get("at", "")
    for pattern in ("%Y-%m-%dT%H-%M-%SZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(at, pattern).replace(tzinfo=timezone.utc)
            break
        except (TypeError, ValueError):
            pass
    else:
        try:
            dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("timestamp needs a timezone")
        except (AttributeError, TypeError, ValueError):
            dt = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            return {"file": path.name, "at": dt.isoformat(), "time_basis": "file modified"}
    return {"file": path.name, "at": dt.astimezone(timezone.utc).isoformat(),
            "time_basis": "recorded run"}


def _valid_eval(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    meta, summary = data.get("meta"), data.get("summary")
    if not isinstance(meta, dict) or not isinstance(summary, dict) or meta.get("invalid"):
        return False
    arms = meta.get("arms", [])
    if (not isinstance(arms, list) or not all(isinstance(a, str) for a in arms)
            or not {"A", "C"}.issubset(arms)):
        return False
    # The headline is a whole-benchmark comparison. Partial runs stay on disk but
    # never replace it. Capped budgets and deterministic runs are valid, labelled runs.
    for arm in arms:
        if arm not in ("A", "B", "C") or not isinstance(summary.get(arm), dict):
            return False
        stats = summary[arm].get("all", {})
        if not isinstance(stats, dict):
            return False
        if stats.get("n") != 30 or not all(_number(stats.get(k)) for k in
                ("accuracy", "mean_llm_requests", "mean_steps", "duplicate_notifications")):
            return False
        if not 0 <= stats["accuracy"] <= 1 or any(stats[k] < 0 for k in
                ("mean_llm_requests", "mean_steps", "duplicate_notifications")):
            return False
    return True


def latest_results(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"eval": None, "load": None, "load_source": None,
                           "isolation": None, "isolation_source": None,
                           "fencing": None, "fencing_source": None}
    candidates = []
    for path in (root / "eval" / "results").glob("*/summary.json"):
        data = _read(path)
        if ("INVALID" in path.parent.name.upper() or (path.parent / "rows.partial.jsonl").exists()
                or not _valid_eval(data)):
            continue
        source = _source(path, data["meta"])
        candidates.append((source["at"], path.parent.name, data, source))
    if candidates:
        _, name, data, source = max(candidates, key=lambda item: (item[0], item[1]))
        out["eval"] = {**data, "name": name, "source": source}

    for kind in ("load", "isolation", "fencing"):
        found = []
        for path in (root / "bench" / "results").glob(f"{kind}*.json"):
            data = _read(path)
            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            if not isinstance(meta, dict) or meta.get("invalid"):
                continue
            payload = data.get("result") if isinstance(data, dict) and "result" in data else data
            if kind == "load":
                valid = isinstance(payload, list) and bool(payload) and all(
                    isinstance(row, dict) and all(_number(row.get(k)) for k in
                        ("completed", "incidents", "duplicate_notifications", "worker_pairs_per_company"))
                    and all(isinstance(row.get(k), dict) for k in ("memory_reads", "memory_writes"))
                    for row in payload)
            elif kind == "isolation":
                valid = (isinstance(payload, dict) and isinstance(payload.get("ok"), bool)
                         and isinstance(payload.get("leaks"), dict))
            else:
                valid = (isinstance(payload, dict) and isinstance(payload.get("ok"), bool)
                         and _number(payload.get("stale_writes_rejected"))
                         and _number(payload.get("stale_writes_attempted")))
            if not valid:
                continue
            source = _source(path, meta)
            # Keep failed checks: the newest failure must not be hidden by an older pass.
            found.append((source["at"], path.name, payload, source))
        if found:
            _, _, out[kind], out[f"{kind}_source"] = max(found, key=lambda item: (item[0], item[1]))
    return out
