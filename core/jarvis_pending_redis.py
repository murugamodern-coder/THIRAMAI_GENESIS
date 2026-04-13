"""
Redis-backed Jarvis agent pending confirmations + last-undo stack.

Falls back to in-process memory when REDIS_URL is unset or Redis errors (dev / single worker).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

_log = logging.getLogger("thiramai.jarvis_pending")

_PREFIX = "thiramai:jarvis:pending:"
_UNDO_PREFIX = "thiramai:jarvis:undo:"

_memory_pending: dict[str, tuple[float, int, list[dict[str, Any]], int | None]] = {}
_memory_undo: dict[int, tuple[float, list[dict[str, Any]]]] = {}


def _redis():
    try:
        from services.worker_heartbeat import redis_client

        return redis_client()
    except Exception as exc:  # pragma: no cover
        _log.debug("jarvis_pending: no redis: %s", exc)
        return None


def _cleanup_memory_pending() -> None:
    now = time.time()
    dead = [k for k, v in _memory_pending.items() if v[0] < now]
    for k in dead:
        _memory_pending.pop(k, None)


def pending_set(
    pending_id: str,
    *,
    user_id: int,
    tool_calls: list[dict[str, Any]],
    ttl_sec: int,
    context_organization_id: int | None = None,
) -> None:
    uid = int(user_id)
    oid = int(context_organization_id) if context_organization_id is not None and int(context_organization_id) > 0 else None
    payload = json.dumps({"u": uid, "c": tool_calls, "o": oid}, default=str)
    r = _redis()
    if r:
        try:
            r.setex(_PREFIX + pending_id, int(ttl_sec), payload)
            return
        except Exception as exc:
            _log.warning("jarvis pending redis set failed: %s", exc)
    _cleanup_memory_pending()
    _memory_pending[pending_id] = (time.time() + float(ttl_sec), uid, tool_calls, oid)


def pending_pop(pending_id: str, *, user_id: int) -> tuple[list[dict[str, Any]], int | None] | None:
    uid = int(user_id)
    r = _redis()
    if r:
        try:
            key = _PREFIX + pending_id
            raw = r.get(key)
            if not raw:
                return None
            r.delete(key)
            data = json.loads(raw)
            if int(data.get("u") or 0) != uid:
                return None
            calls = data.get("c") if isinstance(data.get("c"), list) else []
            ctx_raw = data.get("o")
            ctx_oid = int(ctx_raw) if ctx_raw is not None and str(ctx_raw).strip().lstrip("-").isdigit() else None
            return calls, ctx_oid
        except Exception as exc:
            _log.warning("jarvis pending redis pop failed: %s", exc)
    _cleanup_memory_pending()
    entry = _memory_pending.pop(pending_id, None)
    if not entry:
        return None
    exp, stored_uid, calls, ctx_oid = entry if len(entry) == 4 else (*entry[:3], None)
    if time.time() > exp or stored_uid != uid:
        return None
    return calls, ctx_oid


def undo_store(user_id: int, ops: list[dict[str, Any]], ttl_sec: int = 3600) -> None:
    """Replace last undo stack for user (most recent Jarvis batch only)."""
    uid = int(user_id)
    if not ops:
        return
    payload = json.dumps({"ops": ops}, default=str)
    r = _redis()
    if r:
        try:
            r.setex(_UNDO_PREFIX + str(uid), int(ttl_sec), payload)
            return
        except Exception as exc:
            _log.warning("jarvis undo redis set failed: %s", exc)
    _memory_undo[uid] = (time.time() + float(ttl_sec), ops)


def undo_pop_stack(user_id: int) -> list[dict[str, Any]] | None:
    uid = int(user_id)
    r = _redis()
    if r:
        try:
            key = _UNDO_PREFIX + str(uid)
            raw = r.get(key)
            if not raw:
                return None
            r.delete(key)
            data = json.loads(raw)
            ops = data.get("ops")
            return ops if isinstance(ops, list) else None
        except Exception as exc:
            _log.warning("jarvis undo redis pop failed: %s", exc)
    entry = _memory_undo.pop(uid, None)
    if not entry:
        return None
    exp, ops = entry
    if time.time() > exp:
        return None
    return ops
