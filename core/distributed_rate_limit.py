"""
Redis-backed global rate limit for horizontal scale (Phase 8).

Default: **100 requests/minute** per authenticated user (JWT ``sub``) or per client IP when
anonymous. Skipped when ``REDIS_URL`` is unset (use in-memory limits in ``RateLimitMiddleware``).

Disable with ``THIRAMAI_RL_REDIS_GLOBAL=0``.
"""

from __future__ import annotations

import os
import time

from jose.exceptions import ExpiredSignatureError, JWTError
from starlette.requests import Request

from core.auth import decode_access_token

_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)


def _truthy_global_enabled() -> bool:
    if (os.getenv("THIRAMAI_RL_REDIS_GLOBAL") or "").strip() == "0":
        return False
    return True


def _limit_per_minute() -> int:
    try:
        return max(10, int((os.getenv("THIRAMAI_RL_GLOBAL_PER_MINUTE") or "100").strip()))
    except ValueError:
        return 100


def _client_ip(request: Request) -> str:
    if (os.getenv("THIRAMAI_RL_TRUST_X_FORWARDED_FOR") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        xff = (request.headers.get("x-forwarded-for") or "").strip()
        if xff:
            return xff.split(",")[0].strip()[:128] or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _bearer(request: Request) -> str | None:
    h = (request.headers.get("authorization") or "").strip()
    if len(h) > 7 and h[:7].lower() == "bearer ":
        return h[7:].strip()
    return None


def _path_exempt(path: str) -> bool:
    p = path or ""
    if p in ("/", ""):
        return True
    # Login/register/refresh: tighter in-memory limits on this router; avoid double NAT throttling here.
    if p.startswith("/auth"):
        return True
    for pref in _EXEMPT_PREFIXES:
        if p == pref or p.startswith(pref + "/"):
            return True
    if p.startswith("/static/") or p.startswith("/public/"):
        return True
    return False


def check_distributed_rate_limit(request: Request) -> tuple[bool, str | None]:
    """
    Return (allowed, error_detail). When Redis is disabled or path exempt, always allowed.
    """
    if not _truthy_global_enabled():
        return True, None

    from services.worker_heartbeat import redis_client

    r = redis_client()
    if r is None:
        return True, None

    path = request.url.path or ""
    if _path_exempt(path):
        return True, None

    ident: str
    kind = "ip"
    token = _bearer(request)
    if token:
        try:
            claims = decode_access_token(token)
            sub = str(claims.get("sub") or "").strip()
            if sub:
                ident = sub
                kind = "u"
        except ExpiredSignatureError:
            ident = _client_ip(request)
            kind = "ip"
        except JWTError:
            ident = _client_ip(request)
            kind = "ip"
    else:
        ident = _client_ip(request)

    minute = int(time.time()) // 60
    limit = _limit_per_minute()
    key = f"thiramai:rl:global:{kind}:{ident}:{minute}"
    try:
        n = int(r.incr(key))
        if n == 1:
            r.expire(key, 120)
        if n > limit:
            return False, f"Global rate limit exceeded ({limit}/minute per {'user' if kind == 'u' else 'client'})."
        return True, None
    except Exception:
        return True, None


def describe_distributed_limiter() -> str:
    """For registry / ops docs."""
    return (
        "When REDIS_URL is set and THIRAMAI_RL_REDIS_GLOBAL is not 0, "
        f"requests are capped at {_limit_per_minute()}/min per JWT user id or client IP "
        "(exempt: /health*, /docs*, /static/*, /public/*)."
    )
