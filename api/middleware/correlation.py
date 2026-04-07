"""X-Correlation-ID: propagate or generate for tracing policy + audit."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.observability import clear_log_context, set_log_context

HEADER_NAME = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Ensures every request has a correlation id:

    - If ``X-Correlation-ID`` is present, it is echoed (trimmed, max 128 chars).
    - Otherwise a new UUID4 is generated.

    Stored on ``request.state.correlation_id`` and returned on the response header.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        raw = (request.headers.get(HEADER_NAME) or "").strip()
        if raw and len(raw) <= 128:
            cid = raw
        elif raw:
            cid = raw[:128]
        else:
            cid = str(uuid.uuid4())
        request.state.correlation_id = cid
        set_log_context(trace_id=cid)
        try:
            response = await call_next(request)
        finally:
            clear_log_context()
        response.headers[HEADER_NAME] = cid
        return response
