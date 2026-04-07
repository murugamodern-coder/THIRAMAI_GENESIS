"""HTTP request/response logging (JSON lines when ``THIRAMAI_LOG_JSON=1``)."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_log = logging.getLogger("thiramai.http")


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _json_logs() -> bool:
    return _truthy("THIRAMAI_LOG_JSON")


def _should_skip(path: str) -> bool:
    return path in ("/health/live", "/favicon.ico")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Emits one structured line per request when ``THIRAMAI_LOG_JSON=1``.

    Uses ``X-Correlation-ID`` from ``request.state`` (set by ``CorrelationIdMiddleware`` outer layer).
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not _json_logs():
            return await call_next(request)

        path = request.url.path or ""
        if _should_skip(path):
            return await call_next(request)

        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            ms = (time.perf_counter() - t0) * 1000.0
            cid = getattr(request.state, "correlation_id", None)
            payload = {
                "event": "http_request",
                "method": request.method,
                "path": path,
                "status_code": 500,
                "duration_ms": round(ms, 2),
                "error": "exception",
            }
            if cid:
                payload["correlation_id"] = cid
            _log.info(json.dumps(payload, ensure_ascii=False))
            raise

        ms = (time.perf_counter() - t0) * 1000.0
        cid = getattr(request.state, "correlation_id", None)
        payload = {
            "event": "http_request",
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": round(ms, 2),
        }
        if cid:
            payload["correlation_id"] = cid
        _log.info(json.dumps(payload, ensure_ascii=False))
        return response
