"""Return 403 for dangerous tool routes in production (routers are also omitted — this catches direct probes)."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.dependencies import try_resolve_current_user_from_access_token
from core.dangerous_routes import is_dangerous_public_path, production_blocks_dangerous_routes
from services.security_audit import EVENT_DANGEROUS_ENDPOINT, record_security_audit_event

_log = logging.getLogger(__name__)


def _bearer_token(request: Request) -> str | None:
    h = (request.headers.get("authorization") or "").strip()
    if len(h) > 7 and h[:7].lower() == "bearer ":
        return h[7:].strip()
    return None


def _user_id_from_request(request: Request) -> int | None:
    cur = getattr(request.state, "current_user", None)
    if cur is not None and getattr(cur, "id", None) is not None:
        try:
            uid = int(cur.id)
            return uid if uid > 0 else None
        except (TypeError, ValueError):
            return None
    tok = _bearer_token(request)
    if not tok:
        return None
    try:
        u = try_resolve_current_user_from_access_token(tok)
        if u is None:
            return None
        uid = int(u.id)
        return uid if uid > 0 else None
    except Exception:
        return None


class DangerousRouteBlockMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        path = request.url.path or ""
        if production_blocks_dangerous_routes() and is_dangerous_public_path(path):
            ip = request.client.host if request.client and request.client.host else None
            uid = _user_id_from_request(request)
            try:
                await asyncio.to_thread(
                    record_security_audit_event,
                    event_type=EVENT_DANGEROUS_ENDPOINT,
                    user_id=uid,
                    ip_address=ip,
                    path=path,
                    details={"reason": "production_block"},
                )
            except Exception:
                _log.debug("security_audit_dangerous_route_failed", exc_info=True)
            return JSONResponse(
                status_code=403,
                content={"detail": "This endpoint is disabled in production."},
            )
        return await call_next(request)
