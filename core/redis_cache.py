"""
JSON cache helpers on Redis (Phase 8 dashboard / Life OS snapshot caching).

Uses ``REDIS_URL``; no-ops when unset or Redis unavailable.
"""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_TTL = 300


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
