"""
Redis-backed liveness for background workers (job queue, alert scheduler, etc.).

Keys: ``thiramai:heartbeat:<role>:<instance_id>`` with TTL (default 120s).
Readiness uses SCAN for pattern ``thiramai:heartbeat:<role>:*``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from typing import Any

_log = logging.getLogger(__name__)

_HEARTBEAT_PREFIX = "thiramai:heartbeat"


def _redis_url() -> str:
    return (os.getenv("REDIS_URL") or "").strip()


def redis_client():
    url = _redis_url()
    if not url:
        return None
    try:
        import redis

        return redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0)
    except Exception as exc:
        _log.warning("worker_heartbeat: redis client failed: %s", exc)
        return None


def worker_instance_id() -> str:
    raw = (os.getenv("THIRAMAI_WORKER_INSTANCE_ID") or "").strip()
    if raw:
        return raw[:200]
    return f"{socket.gethostname()}:{os.getpid()}"


def heartbeat_ttl_sec() -> int:
    try:
        return max(30, int((os.getenv("THIRAMAI_HEARTBEAT_TTL_SEC") or "120").strip()))
    except ValueError:
        return 120


def touch_heartbeat(worker_role: str) -> bool:
    """
    Refresh heartbeat for this process. ``worker_role`` examples: ``job_worker``, ``alert_worker``.
    """
    r = redis_client()
    if r is None:
        return False
    role = (worker_role or "unknown").strip().replace(" ", "_")[:64]
    wid = worker_instance_id()
    key = f"{_HEARTBEAT_PREFIX}:{role}:{wid}"
    ttl = heartbeat_ttl_sec()
    payload = json.dumps(
        {
            "ts": time.time(),
            "role": role,
            "instance_id": wid,
        },
        separators=(",", ":"),
    )
    try:
        r.setex(key, ttl, payload)
        return True
    except Exception as exc:
        _log.warning("worker_heartbeat: SETEX failed: %s", exc)
        return False


def redis_ping_ok() -> tuple[bool, str]:
    r = redis_client()
    if r is None:
        return False, "REDIS_URL not set or client unavailable"
    try:
        if r.ping():
            return True, "PONG"
        return False, "PING returned false"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def any_heartbeat_for_role(worker_role: str) -> bool:
    """True if at least one non-expired heartbeat key exists for the role."""
    r = redis_client()
    if r is None:
        return False
    role = (worker_role or "").strip().replace(" ", "_")[:64]
    pattern = f"{_HEARTBEAT_PREFIX}:{role}:*"
    try:
        for key in r.scan_iter(match=pattern, count=32):
            if r.ttl(key) > 0:
                return True
        return False
    except Exception as exc:
        _log.warning("worker_heartbeat: scan failed: %s", exc)
        return False


def expected_worker_roles_from_env() -> list[str]:
    raw = (os.getenv("THIRAMAI_HEALTH_EXPECT_WORKERS") or "").strip()
    if not raw:
        return []
    return [p.strip().replace(" ", "_") for p in raw.split(",") if p.strip()]


def newest_heartbeat_payload_ts(worker_role: str) -> tuple[float | None, str]:
    """
    Latest ``ts`` field from any **live** heartbeat key for ``worker_role`` (Redis TTL > 0).

    Returns ``(None, reason)`` when Redis is missing, no keys, or payloads are invalid.
    """
    r = redis_client()
    if r is None:
        return None, "redis_unavailable"
    role = (worker_role or "").strip().replace(" ", "_")[:64]
    pattern = f"{_HEARTBEAT_PREFIX}:{role}:*"
    newest: float | None = None
    try:
        for key in r.scan_iter(match=pattern, count=64):
            try:
                if r.ttl(key) <= 0:
                    continue
                raw = r.get(key)
                if not raw:
                    continue
                data = json.loads(raw)
                ts = float(data.get("ts") or 0)
                if ts > 0:
                    newest = ts if newest is None else max(newest, ts)
            except Exception:
                continue
    except Exception as exc:
        return None, f"scan_failed:{type(exc).__name__}"
    if newest is None:
        return None, "no_live_heartbeat"
    return newest, "ok"


def job_worker_heartbeat_age_seconds() -> tuple[float | None, str]:
    """Seconds since newest ``job_worker`` heartbeat ``ts``; ``None`` if unknown."""
    ts, msg = newest_heartbeat_payload_ts("job_worker")
    if ts is None:
        return None, msg
    return max(0.0, time.time() - ts), "ok"


def workers_ready_detail() -> dict[str, Any]:
    roles = expected_worker_roles_from_env()
    if not roles:
        return {"configured": False, "roles": [], "ok": True, "detail": "THIRAMAI_HEALTH_EXPECT_WORKERS unset"}
    out: dict[str, Any] = {"configured": True, "roles": {}, "ok": True}
    for role in roles:
        alive = any_heartbeat_for_role(role)
        out["roles"][role] = {"alive": alive}
        if not alive:
            out["ok"] = False
    return out
