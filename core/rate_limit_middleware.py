"""
Sliding-window rate limiting (stdlib + Starlette; no slowapi).

Tier buckets (per Day 2 spec), plus stricter paths:
- ``POST /chat/query``: JWT required; per-user ``THIRAMAI_RL_CHAT_QUERY_PER_USER_PER_MINUTE`` (default 5).
- ``POST /ai/goal``: per-user or per-IP ``THIRAMAI_RL_AI_GOAL_PER_USER_PER_MINUTE`` (default 20).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from jose.exceptions import ExpiredSignatureError, JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.auth import decode_access_token
from core.distributed_rate_limit import check_distributed_rate_limit

_RL_LOCK = Lock()
_HITS: dict[tuple[str, str], list[float]] = defaultdict(list)
_WINDOW_SEC = 60.0

TIER_AUTH = 5
TIER_CHAT = 20
TIER_RESEARCH = 10
TIER_AUTONOMY = 3
TIER_CRUD = 60

_WWW_BEARER = {"WWW-Authenticate": "Bearer"}
_LOG = logging.getLogger(__name__)
_WARNED_NO_PROXY_ALLOWLIST = False
_ProxyNet = ipaddress.IPv4Network | ipaddress.IPv6Network


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int, *, min_v: int, max_v: int) -> int:
    try:
        v = int((os.getenv(name) or str(default)).strip())
    except ValueError:
        v = default
    return max(min_v, min(max_v, v))


def _trusted_proxy_networks() -> list[_ProxyNet]:
    raw = (os.getenv("THIRAMAI_TRUSTED_PROXY_IPS") or "").strip()
    if not raw:
        return []
    nets: list[_ProxyNet] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            continue
    return nets


def _is_trusted_proxy(remote_host: str, trusted_nets: list[_ProxyNet]) -> bool:
    if not remote_host or not trusted_nets:
        return False
    try:
        rip = ipaddress.ip_address(remote_host)
    except ValueError:
        return False
    return any(rip in net for net in trusted_nets)


def _leftmost_xff_ip(request: Request) -> str | None:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if not xff:
        return None
    cand = xff.split(",")[0].strip()
    if not cand:
        return None
    try:
        ipaddress.ip_address(cand)
    except ValueError:
        return None
    return cand[:128]


def _client_key(request: Request) -> str:
    global _WARNED_NO_PROXY_ALLOWLIST
    remote_host = request.client.host if request.client and request.client.host else "unknown"
    if not _truthy("THIRAMAI_RL_TRUST_X_FORWARDED_FOR"):
        return remote_host

    trusted_nets = _trusted_proxy_networks()
    if not trusted_nets and not _WARNED_NO_PROXY_ALLOWLIST:
        _LOG.warning(
            {
                "event": "rate_limit.security_warning",
                "msg": "X-Forwarded-For trust enabled with no proxy allowlist",
            }
        )
        _WARNED_NO_PROXY_ALLOWLIST = True
    if not _is_trusted_proxy(remote_host, trusted_nets):
        return remote_host
    return _leftmost_xff_ip(request) or remote_host


def _prune_and_count(key: tuple[str, str], now: float, window: float, limit: int) -> bool:
    """Return True if request is allowed (under limit)."""
    with _RL_LOCK:
        arr = _HITS[key]
        cutoff = now - window
        arr[:] = [t for t in arr if t >= cutoff]
        if len(arr) >= limit:
            return False
        arr.append(now)
        return True


def _bearer_token(request: Request) -> str | None:
    h = (request.headers.get("authorization") or "").strip()
    if len(h) > 7 and h[:7].lower() == "bearer ":
        return h[7:].strip()
    return None


def _tier_for_path(path: str) -> tuple[str, int] | None:
    """Return (hit_bucket_name, limit_per_minute) or None."""
    p = path or ""
    if p.startswith("/auth"):
        lim = _int_env("THIRAMAI_RL_AUTH_PER_MINUTE", TIER_AUTH, min_v=1, max_v=300)
        return ("tier_auth", lim)
    if p.startswith("/org"):
        lim = _int_env("THIRAMAI_RL_CRUD_PER_MINUTE", TIER_CRUD, min_v=1, max_v=60_000)
        return ("tier_crud", lim)
    if p.startswith("/brain") or p.startswith("/chat") or p.startswith("/ai") or p.startswith("/v1/ai"):
        lim = _int_env("THIRAMAI_RL_CHAT_PER_MINUTE", TIER_CHAT, min_v=1, max_v=600)
        return ("tier_chat", lim)
    if p.startswith("/research") or p.startswith("/research-loop") or p.startswith("/invention-loop"):
        lim = _int_env("THIRAMAI_RL_RESEARCH_PER_MINUTE", TIER_RESEARCH, min_v=1, max_v=600)
        return ("tier_research", lim)
    if p.startswith("/autonomy"):
        lim = _int_env("THIRAMAI_RL_AUTONOMY_PER_MINUTE", TIER_AUTONOMY, min_v=1, max_v=600)
        return ("tier_autonomy", lim)
    if p.startswith("/inventory") or p.startswith("/billing") or p.startswith("/personal"):
        lim = _int_env("THIRAMAI_RL_CRUD_PER_MINUTE", TIER_CRUD, min_v=1, max_v=60_000)
        return ("tier_crud", lim)
    return None


def _tier_identity_key(request: Request, tier_bucket: str, token: str | None) -> str:
    if tier_bucket == "tier_auth":
        return f"ip:{_client_key(request)}"
    if token:
        try:
            claims = decode_access_token(token)
            sub = str(claims.get("sub") or "").strip() or "anon"
            return f"uid:{sub}"
        except (ExpiredSignatureError, JWTError):
            return f"ip:{_client_key(request)}"
    return f"ip:{_client_key(request)}"


async def _audit_rate_limit_exceeded(
    request: Request,
    *,
    bucket: str,
    limit_per_minute: int,
    path: str,
) -> None:
    try:
        from services.security_audit import EVENT_RATE_LIMIT_EXCEEDED, record_security_audit_event

        tok = _bearer_token(request)
        user_id: int | None = None
        if tok:
            try:
                claims = await asyncio.to_thread(decode_access_token, tok)
                raw = str(claims.get("sub") or "").strip()
                if raw.isdigit():
                    user_id = int(raw)
            except Exception:
                pass
        ip = request.client.host if request.client and request.client.host else None
        await asyncio.to_thread(
            record_security_audit_event,
            event_type=EVENT_RATE_LIMIT_EXCEEDED,
            user_id=user_id,
            ip_address=ip,
            path=path,
            details={"bucket": bucket, "limit_per_minute": limit_per_minute},
        )
    except Exception:
        _LOG.debug("security_audit_rate_limit_failed", exc_info=True)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """429 when limits exceeded; 401 on /chat/query when JWT missing, expired, or invalid."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path or ""

        allowed, gmsg = await asyncio.to_thread(check_distributed_rate_limit, request)
        if not allowed:
            await _audit_rate_limit_exceeded(
                request,
                bucket="redis_global_per_minute",
                limit_per_minute=-1,
                path=path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": gmsg or "Rate limit exceeded.",
                    "bucket": "redis_global_per_minute",
                },
            )

        if request.method == "POST" and path.rstrip("/") == "/ai/goal":
            token = _bearer_token(request)
            ck = _client_key(request)
            if token:
                try:
                    claims = await asyncio.to_thread(decode_access_token, token)
                    sub = str(claims.get("sub") or "").strip() or "anon"
                    key = (f"uid:{sub}", "ai_goal")
                except (ExpiredSignatureError, JWTError):
                    key = (f"ip:{ck}", "ai_goal_ip")
            else:
                key = (f"ip:{ck}", "ai_goal_ip")
            limit = _int_env("THIRAMAI_RL_AI_GOAL_PER_USER_PER_MINUTE", TIER_CHAT, min_v=1, max_v=600)
            now = time.monotonic()
            if not _prune_and_count(key, now, _WINDOW_SEC, limit):
                await _audit_rate_limit_exceeded(
                    request, bucket=key[1], limit_per_minute=limit, path=path
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded for POST /ai/goal. Try again shortly.",
                        "bucket": key[1],
                        "limit_per_minute": limit,
                    },
                )
            return await call_next(request)

        if request.method == "POST" and path.rstrip("/") == "/chat/query":
            token = _bearer_token(request)
            if not token:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Not authenticated"},
                    headers=_WWW_BEARER,
                )
            try:
                claims = await asyncio.to_thread(decode_access_token, token)
            except ExpiredSignatureError:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token expired"},
                    headers=_WWW_BEARER,
                )
            except JWTError:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid token"},
                    headers=_WWW_BEARER,
                )
            sub = str(claims.get("sub") or "").strip() or "anon"
            limit = _int_env("THIRAMAI_RL_CHAT_QUERY_PER_USER_PER_MINUTE", 5, min_v=1, max_v=600)
            now = time.monotonic()
            key = (f"uid:{sub}", "chat_query")
            if not _prune_and_count(key, now, _WINDOW_SEC, limit):
                await _audit_rate_limit_exceeded(
                    request, bucket="chat_query_user", limit_per_minute=limit, path=path
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded for POST /chat/query. Try again shortly.",
                        "bucket": "chat_query_user",
                        "limit_per_minute": limit,
                    },
                )
            return await call_next(request)

        tier = _tier_for_path(path)
        if tier is not None:
            bucket_name, limit = tier
            tok = _bearer_token(request)
            ident = _tier_identity_key(request, bucket_name, tok)
            now = time.monotonic()
            key = (ident, bucket_name)
            if not _prune_and_count(key, now, _WINDOW_SEC, limit):
                await _audit_rate_limit_exceeded(
                    request, bucket=bucket_name, limit_per_minute=limit, path=path
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Try again shortly.",
                        "bucket": bucket_name,
                        "limit_per_minute": limit,
                    },
                )
            return await call_next(request)

        tok = _bearer_token(request)
        if tok:
            try:
                claims = await asyncio.to_thread(decode_access_token, tok)
                oid = str(claims.get("active_org_id") or claims.get("org_id") or "").strip()
                if oid:
                    org_limit = _int_env("THIRAMAI_RL_ORG_PER_MINUTE", 600, min_v=30, max_v=60_000)
                    now = time.monotonic()
                    if not _prune_and_count((f"org:{oid}", "org_all"), now, _WINDOW_SEC, org_limit):
                        await _audit_rate_limit_exceeded(
                            request, bucket="org_all", limit_per_minute=org_limit, path=path
                        )
                        return JSONResponse(
                            status_code=429,
                            content={
                                "detail": "Organization rate limit exceeded. Try again shortly.",
                                "bucket": "org_all",
                                "limit_per_minute": org_limit,
                            },
                        )
            except Exception:
                pass
        return await call_next(request)
