"""
Stage 5 — Sovereign journal: chain-of-thought steps and background action trail for the
executive digest and real-time dashboard.

Persists under ``var/sovereign/`` (gitignored). Optional Redis list ``thiramai:sovereign:cot`` when
``REDIS_URL`` is set (SSE / multi-worker tail).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

_LOG = __import__("logging").getLogger(__name__)


def _truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def sovereign_stage5_enabled() -> bool:
    """Master flag for Stage 5 journaling (default on when unset for new installs)."""
    raw = (os.getenv("THIRAMAI_SOVEREIGN_STAGE5") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sovereign_dir() -> Path:
    p = _root() / "var" / "sovereign"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _redis():
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis

        return redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0)
    except Exception:
        return None


def record_cot_step(
    *,
    agent: str,
    phase: str,
    detail: str,
    organization_id: int | None = None,
    trace_id: str | None = None,
) -> None:
    """Append one CoT step (orchestrator, swarm, world_scan, etc.)."""
    if not sovereign_stage5_enabled():
        return
    entry: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts": time.time(),
        "agent": (agent or "")[:128],
        "phase": (phase or "")[:128],
        "detail": (detail or "")[:4000],
        "organization_id": int(organization_id) if organization_id is not None else None,
        "trace_id": (trace_id or "")[:128] or None,
    }
    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
    try:
        cot_path = _sovereign_dir() / "cot_events.jsonl"
        with cot_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("sovereign_journal: cot append failed: %s", exc)
    r = _redis()
    if r is not None:
        try:
            key = "thiramai:sovereign:cot"
            r.lpush(key, line.strip())
            r.ltrim(key, 0, 499)
        except Exception as exc:
            _LOG.debug("sovereign_journal: redis cot failed: %s", exc)


def record_background_action(
    *,
    category: str,
    summary: str,
    organization_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """One aggregated unit for the daily executive digest (code, factory, ops, world)."""
    if not sovereign_stage5_enabled():
        return
    entry: dict[str, Any] = {
        "ts": time.time(),
        "category": (category or "")[:64],
        "summary": (summary or "")[:2000],
        "organization_id": int(organization_id) if organization_id is not None else None,
        "meta": meta or {},
    }
    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
    try:
        trail_path = _sovereign_dir() / "action_trail.jsonl"
        with trail_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("sovereign_journal: action_trail append failed: %s", exc)


def read_recent_cot(*, limit: int = 200, organization_id: int | None = None) -> list[dict[str, Any]]:
    """Newest last in returned list (chronological order for UI)."""
    path = _sovereign_dir() / "cot_events.jsonl"
    if not path.is_file():
        r = _redis()
        if r is not None:
            try:
                raw_lines = r.lrange("thiramai:sovereign:cot", 0, max(1, min(limit, 500)) - 1)
                parsed: list[dict[str, Any]] = []
                for line in reversed(raw_lines):
                    try:
                        parsed.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                if organization_id is not None:
                    parsed = [x for x in parsed if x.get("organization_id") == organization_id]
                return parsed[-limit:]
            except Exception:
                pass
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    chunk = lines[-max(limit * 2, limit) :]
    out: list[dict[str, Any]] = []
    for line in chunk:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if organization_id is not None and row.get("organization_id") not in (organization_id, None):
            continue
        out.append(row)
    return out[-limit:]


def read_action_trail_since(
    *,
    since_ts: float,
    limit: int = 2000,
    organization_id: int | None = None,
) -> list[dict[str, Any]]:
    path = _sovereign_dir() / "action_trail.jsonl"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if float(row.get("ts") or 0) < since_ts:
            continue
        if organization_id is not None and row.get("organization_id") not in (organization_id, None):
            continue
        out.append(row)
    return out
