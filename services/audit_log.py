"""
Append-only **system_audit_logs** for sensitive operations (auth, inventory, financial execution).

Never store passwords, tokens, or full PII in ``metadata`` — only opaque ids and action context.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import SystemAuditLog

_log = logging.getLogger("thiramai.audit")

# Stable action names for reporting / SIEM
ACTION_LOGIN_SUCCESS = "login_success"
ACTION_LOGIN_FAILURE = "login_failure"
ACTION_REGISTER = "register"
ACTION_STOCK_UPDATE = "stock_update"
ACTION_FINANCIAL_EXECUTION = "financial_execution"


def _json_safe(meta: dict[str, Any]) -> dict[str, Any]:
    try:
        out = json.loads(json.dumps(meta, default=str))
        if not isinstance(out, dict):
            return {}
        return dict(list(out.items())[:40])
    except (TypeError, ValueError):
        return {}


def record_system_audit(
    *,
    action: str,
    outcome: str = "success",
    organization_id: int | None = None,
    user_id: int | None = None,
    resource_type: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
    session: Session | None = None,
) -> int | None:
    """
    Insert one audit row. Returns id or None if DB unavailable / insert failed.

    If ``session`` is provided, the caller must commit; otherwise a short-lived session is used.
    """
    meta = _json_safe(dict(metadata or {}))
    if len(str(meta)) > 8000:
        meta = {"truncated": True}

    row = SystemAuditLog(
        organization_id=int(organization_id) if organization_id is not None else None,
        user_id=int(user_id) if user_id is not None and user_id > 0 else None,
        action=action[:64],
        outcome=outcome[:32],
        resource_type=(resource_type[:64] if resource_type else None),
        client_ip=(client_ip[:45] if client_ip else None),
        user_agent=(user_agent[:2000] if user_agent else None),
        audit_metadata=meta,
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
        _log.warning("audit_log_insert_failed %s", type(exc).__name__, exc_info=False)
        return None


def client_ip_from_request(client_host: str | None) -> str | None:
    if not client_host:
        return None
    return client_host[:45]
