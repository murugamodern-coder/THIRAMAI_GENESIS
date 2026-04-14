"""Referral / invite codes (Redis)."""

from __future__ import annotations

import json
import logging
import os
import secrets
from typing import Any

_log = logging.getLogger("thiramai.invite")

_PREFIX = "thiramai:invite:"


def _ttl_sec() -> int:
    try:
        return max(86400, int((os.getenv("THIRAMAI_INVITE_TTL_SEC") or str(90 * 86400)).strip()))
    except ValueError:
        return 90 * 86400


def create_invite_code(*, inviter_user_id: int, organization_id: int) -> str | None:
    """Store invite payload; returns opaque code or None if Redis unavailable."""
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r is None:
            return None
    except Exception as exc:
        _log.debug("invite redis: %s", exc)
        return None
    code = secrets.token_urlsafe(8)[:12].replace("-", "x")
    payload = {"u": int(inviter_user_id), "o": int(organization_id)}
    try:
        r.setex(f"{_PREFIX}{code}", _ttl_sec(), json.dumps(payload))
        return code
    except Exception as exc:
        _log.warning("invite set failed: %s", exc)
        return None


def peek_invite(code: str) -> dict[str, Any] | None:
    raw = (code or "").strip()
    if not raw:
        return None
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r is None:
            return None
        blob = r.get(f"{_PREFIX}{raw}")
        if not blob:
            return None
        return json.loads(blob) if isinstance(blob, str) else json.loads(blob.decode())
    except Exception:
        return None
