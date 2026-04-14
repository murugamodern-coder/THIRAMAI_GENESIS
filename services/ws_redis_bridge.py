"""
Optional Redis pub/sub fan-out for multi-instance WebSocket scaling.

Publishers call ``publish_user_channel`` when ``THIRAMAI_WS_REDIS_FANOUT=1``.
Subscribers must run a matching consumer (separate process / worker) in full multi-node setups.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_log = logging.getLogger("thiramai.ws_redis")


def _enabled() -> bool:
    return (os.getenv("THIRAMAI_WS_REDIS_FANOUT") or "").strip().lower() in ("1", "true", "yes", "on")


def publish_user_channel(kind: str, user_id: int, payload: dict[str, Any]) -> bool:
    """Publish JSON to ``thiramai:ws:{kind}:{user_id}`` for cross-node fan-out."""
    if not _enabled():
        return False
    uid = int(user_id)
    if uid <= 0:
        return False
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r is None:
            return False
        ch = f"thiramai:ws:{(kind or 'generic').strip()[:32]}:{uid}"
        r.publish(ch, json.dumps(payload, default=str))
        return True
    except Exception as exc:
        _log.debug("ws redis publish failed: %s", exc)
        return False
