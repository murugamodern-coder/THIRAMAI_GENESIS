"""Reject oversized JSON bodies on sensitive ``/ai/*`` POST routes early."""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class AiPayloadLimitMiddleware(BaseHTTPMiddleware):
    """Default max 512 KiB for POST/PUT/PATCH under ``/ai/`` (override via env)."""

    def __init__(self, app, max_bytes: int | None = None) -> None:
        super().__init__(app)
        raw = os.getenv("THIRAMAI_AI_MAX_BODY_BYTES", "").strip()
        if max_bytes is not None:
            self._max = max(1024, int(max_bytes))
        elif raw:
            self._max = max(1024, int(raw))
        else:
            self._max = 512 * 1024

    async def dispatch(self, request: Request, call_next):
        path = request.url.path or ""
        if path.startswith("/ai/") and request.method in {"POST", "PUT", "PATCH"}:
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > self._max:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (max {self._max} bytes for /ai/*)"},
                )
        return await call_next(request)
