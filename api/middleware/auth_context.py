"""Attach JWT principal to request.state for decorator-style permission checks."""

from __future__ import annotations

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.dependencies import try_resolve_current_user_from_access_token


def _bearer_from_request(request: Request) -> str | None:
    auth = (request.headers.get("authorization") or "").strip()
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


class AuthContextMiddleware(BaseHTTPMiddleware):
    """
    Best-effort auth context middleware.

    - Parses Authorization: Bearer <jwt>
    - Resolves user principal (including token expiry handling via existing decoder)
    - Stores principal or None at request.state.current_user
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        token = _bearer_from_request(request)
        request.state.current_user = try_resolve_current_user_from_access_token(token)
        return await call_next(request)
