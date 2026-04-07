"""
Production error sanitization: avoid leaking stack traces, paths, and DB internals in HTTP bodies.

Enable with ``THIRAMAI_SAFE_ERRORS=1`` (recommended behind a reverse proxy in production).
Full detail is still logged via the standard logging stack.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

_log = logging.getLogger("thiramai.safe_errors")


def safe_errors_enabled() -> bool:
    return (os.getenv("THIRAMAI_SAFE_ERRORS") or "").strip().lower() in ("1", "true", "yes", "on")


def _generic_detail(status_code: int) -> str:
    if status_code == 401:
        return "Authentication required or credentials invalid."
    if status_code == 403:
        return "Access denied."
    if status_code == 404:
        return "Resource not found."
    if status_code == 409:
        return "Request conflicts with current state."
    if status_code == 422:
        return "Validation failed."
    if status_code == 429:
        return "Too many requests."
    if status_code == 502:
        return "Upstream service error."
    if status_code == 503:
        return "Service temporarily unavailable."
    if status_code >= 500:
        return "An internal error occurred."
    return "Request could not be completed."


def sanitize_http_exception(exc: HTTPException) -> dict[str, Any]:
    """Return a JSON-serializable body; mask ``detail`` when safe mode is on."""
    if not safe_errors_enabled():
        return {"detail": jsonable_encoder(exc.detail)}
    if exc.status_code == 422 and isinstance(exc.detail, (list, dict)):
        return {"detail": _generic_detail(422), "errors": "redacted"}
    return {"detail": _generic_detail(exc.status_code)}


def merge_response_headers(exc: HTTPException) -> dict[str, str] | None:
    """Preserve ``WWW-Authenticate`` and other headers on auth errors."""
    h = getattr(exc, "headers", None)
    if not h:
        return None
    return {str(k): str(v) for k, v in h.items()}


def log_server_exception(request_path: str, exc: BaseException) -> None:
    _log.exception("unhandled_exception path=%s type=%s", request_path, type(exc).__name__)
