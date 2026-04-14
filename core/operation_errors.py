"""Structured logging for swallowed subsystem failures (no silent passes in prod-critical paths)."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from core.observability import log_structured

_log = logging.getLogger("thiramai.ops")


def log_subsystem_failure(
    subsystem: str,
    exc: BaseException,
    *,
    request_id: str | None = None,
    user_id: int | None = None,
    organization_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log exception with trace_id context; use instead of bare ``except: pass``."""
    fields: dict[str, Any] = {
        "subsystem": subsystem,
        "error_type": type(exc).__name__,
        "error": str(exc)[:2000],
    }
    if request_id:
        fields["request_id"] = request_id
    if user_id is not None:
        fields["user_id"] = user_id
    if organization_id is not None:
        fields["organization_id"] = organization_id
    if extra:
        fields.update({k: v for k, v in extra.items() if v is not None})
    log_structured("subsystem_failure", **fields)
    _log.warning(
        "subsystem_failure %s: %s",
        subsystem,
        "".join(traceback.format_exception_only(type(exc), exc)).strip(),
    )
