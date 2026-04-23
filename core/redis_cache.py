"""
JSON cache helpers on Redis (Phase 8 dashboard / Life OS snapshot caching).

Uses ``REDIS_URL``; no-ops when unset or Redis unavailable.

``get_redis()`` returns a shared **async** Redis client (``redis.asyncio``) for LPUSH/LRANGE style APIs.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_TTL = 300

_async_redis: Any = None


async def get_redis() -> Any | None:
    """
    Singleton async Redis client for conversation memory and similar.

    Returns ``None`` when ``REDIS_URL`` is unset or the client cannot be created.
    """
    global _async_redis
    if _async_redis is not None:
        return _async_redis
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis.asyncio as aioredis

        _async_redis = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
        )
        return _async_redis
    except Exception as exc:
        _log.warning("get_redis async client failed: %s", exc)
        return None


def snapshot_cache_ttl_sec() -> int:
    import os

    try:
        return max(30, int((os.getenv("THIRAMAI_SNAPSHOT_CACHE_TTL_SEC") or str(_DEFAULT_TTL)).strip()))
    except ValueError:
        return _DEFAULT_TTL


def cache_get_json(key: str) -> Any | None:
    from services.worker_heartbeat import redis_client

    r = redis_client()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        _log.debug("redis_cache get failed: %s", exc)
        return None


def cache_set_json(key: str, value: Any, *, ttl_sec: int | None = None) -> bool:
    from services.worker_heartbeat import redis_client

    r = redis_client()
    if r is None:
        return False
    ttl = ttl_sec if ttl_sec is not None else snapshot_cache_ttl_sec()
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        r.setex(key, int(ttl), payload)
        return True
    except Exception as exc:
        _log.debug("redis_cache set failed: %s", exc)
        return False


def cache_delete(key: str) -> bool:
    from services.worker_heartbeat import redis_client

    r = redis_client()
    if r is None:
        return False
    try:
        r.delete(key)
        return True
    except Exception:
        return False
