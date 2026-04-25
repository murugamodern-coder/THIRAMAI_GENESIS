"""Persist security-relevant events to ``security_audit_logs`` (best-effort; never raises to callers)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import SecurityAuditLog

_log = logging.getLogger("thiramai.security_audit")

EVENT_FAILED_LOGIN = "failed_login"
EVENT_PERMISSION_DENIED = "permission_denied"
EVENT_RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
EVENT_DANGEROUS_ENDPOINT = "dangerous_endpoint_attempt"


def _json_safe(meta: dict[str, Any]) -> dict[str, Any]:
    try:
        out = json.loads(json.dumps(meta, default=str))
        if not isinstance(out, dict):
            return {}
        return dict(list(out.items())[:50])
    except (TypeError, ValueError):
        return {}


def record_security_audit_event(
    *,
    event_type: str,
    user_id: int | None = None,
    ip_address: str | None = None,
    path: str,
    details: dict[str, Any] | None = None,
    session: Session | None = None,
) -> int | None:
    """Insert one row; returns id or None on failure."""
    det = _json_safe(dict(details or {}))
    if len(str(det)) > 12_000:
        det = {"truncated": True}

    row = SecurityAuditLog(
        event_type=(event_type or "unknown")[:128],
        user_id=int(user_id) if user_id is not None and user_id > 0 else None,
        ip_address=(ip_address[:45] if ip_address else None),
        path=(path or "")[:2048],
        details=det,
    )

    def _do(sess: Session) -> int:
        sess.add(row)
        sess.flush()
        return int(row.id)

    try:
        if session is not None:
            return _do(session)
        factory = get_session_factory()
        if factory is None:
            return None
        with factory() as sess:
            with sess.begin():
                return _do(sess)
    except Exception as exc:
        _log.warning("security_audit_insert_failed %s", type(exc).__name__, exc_info=False)
        return None
