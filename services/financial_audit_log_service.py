"""Append-only financial audit rows (no deletes via this service)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import FinancialAuditLog

_log = logging.getLogger("thiramai.financial_audit")


def append_financial_audit_log(
    session: Session,
    *,
    action: str,
    user_id: int | None,
    organization_id: int | None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    entity_type: str = "",
    entity_id: int | None = None,
    correlation_id: str | None = None,
) -> int | None:
    """Insert one row; returns id or None on failure."""
    try:
        row = FinancialAuditLog(
            user_id=int(user_id) if user_id is not None and int(user_id) > 0 else None,
            organization_id=int(organization_id) if organization_id is not None and int(organization_id) > 0 else None,
            action=(action or "")[:4000],
            entity_type=(entity_type or "")[:128],
            entity_id=int(entity_id) if entity_id is not None else None,
            before_state=dict(before_state or {}),
            after_state=dict(after_state or {}),
            correlation_id=(correlation_id or "")[:128] or None,
        )
        session.add(row)
        session.flush()
        return int(row.id)
    except Exception as exc:
        _log.warning("financial_audit_log insert failed: %s", exc)
        return None


def append_financial_audit_log_sync(
    *,
    action: str,
    user_id: int | None,
    organization_id: int | None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    entity_type: str = "",
    entity_id: int | None = None,
    correlation_id: str | None = None,
) -> int | None:
    factory = get_session_factory()
    if factory is None:
        return None
    with factory() as session:
        with session.begin():
            return append_financial_audit_log(
                session,
                action=action,
                user_id=user_id,
                organization_id=organization_id,
                before_state=before_state,
                after_state=after_state,
                entity_type=entity_type,
                entity_id=entity_id,
                correlation_id=correlation_id,
            )
