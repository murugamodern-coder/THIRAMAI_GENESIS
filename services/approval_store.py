"""Human-in-the-loop (HITL): high-risk actions stored in PostgreSQL, scoped by organization_id."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generator

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import Approval

# Legacy path (no longer written); kept so tooling can archive/migrate old JSON if present.
LEGACY_APPROVALS_JSON = "vault/pending_approvals.json"


class RiskTier(str, Enum):
    low = "low"
    high = "high"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


def _approval_to_dict(a: Approval) -> dict[str, Any]:
    """Shape compatible with previous JSON rows + multi-tenant fields."""
    payload = a.payload if isinstance(a.payload, dict) else dict(a.payload or {})
    return {
        "id": str(a.id),
        "organization_id": int(a.organization_id),
        "action_type": a.action_type,
        "risk_tier": a.risk_tier,
        "status": a.status,
        "summary": a.summary,
        "payload": payload,
        "created_by": int(a.created_by) if a.created_by is not None else None,
        "approved_by": int(a.approved_by) if a.approved_by is not None else None,
        "created_at_utc": a.created_at.isoformat() if a.created_at else None,
        "resolved_at_utc": a.resolved_at.isoformat() if a.resolved_at else None,
    }


@contextmanager
def _db_session() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session or raise if DATABASE_URL is missing."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not set; approvals require PostgreSQL.")
    with factory() as session:
        yield session


def create_pending(
    *,
    organization_id: int,
    action_type: str,
    risk_tier: RiskTier,
    payload: dict[str, Any],
    summary: str,
    created_by: int | None = None,
) -> str:
    """
    Insert a pending approval row for this tenant.

    Returns string UUID for use in URLs and idempotency keys.
    """
    with _db_session() as session:
        with session.begin():
            row = Approval(
                organization_id=int(organization_id),
                action_type=action_type,
                risk_tier=risk_tier.value,
                status=ApprovalStatus.pending.value,
                summary=summary,
                payload=dict(payload),
                created_by=created_by,
            )
            session.add(row)
            session.flush()
            return str(row.id)


def list_pending(*, organization_id: int) -> list[dict[str, Any]]:
    """Return pending approvals for one organization only (multi-tenant boundary)."""
    with _db_session() as session:
        stmt = (
            select(Approval)
            .where(
                Approval.organization_id == int(organization_id),
                Approval.status == ApprovalStatus.pending.value,
            )
            .order_by(Approval.created_at.desc())
        )
        rows = session.execute(stmt).scalars().all()
        return [_approval_to_dict(a) for a in rows]


def get_approval(aid: str, *, organization_id: int) -> dict[str, Any] | None:
    """Load one approval by id if it belongs to the given organization."""
    try:
        key = uuid.UUID(str(aid).strip())
    except ValueError:
        return None
    with _db_session() as session:
        a = session.get(Approval, key)
        if a is None or int(a.organization_id) != int(organization_id):
            return None
        return _approval_to_dict(a)


def resolve(
    aid: str,
    *,
    organization_id: int,
    sovereign_confirm: str,
    approved_by_user_id: int | None = None,
) -> tuple[bool, dict[str, Any] | None, str]:
    """
    Approve (confirm == 'YES') or reject pending approval for this org only.

    Sets approved_by on successful approve; leaves approved_by null on reject.
    Returns (ok, updated_row_dict_or_none, message).
    """
    try:
        key = uuid.UUID(str(aid).strip())
    except ValueError:
        return False, None, "invalid approval id"

    now = datetime.now(timezone.utc)
    with _db_session() as session:
        with session.begin():
            a = session.get(Approval, key)
            if a is None or int(a.organization_id) != int(organization_id):
                return False, None, "approval not found or not pending"
            if a.status != ApprovalStatus.pending.value:
                return False, None, "approval not found or not pending"

            if sovereign_confirm.strip().upper() != "YES":
                a.status = ApprovalStatus.rejected.value
                a.resolved_at = now
                a.approved_by = None
                session.flush()
                return True, _approval_to_dict(a), "rejected"

            a.status = ApprovalStatus.approved.value
            a.resolved_at = now
            a.approved_by = approved_by_user_id
            session.flush()
            d = _approval_to_dict(a)
            d["sovereign_confirm"] = "YES"
            return True, d, "approved"


HIGH_RISK_ACTIONS = frozenset(
    {
        "issue_invoice",
        "brain_action_intent",
        "send_bill",
        "email_send",
        "debt_payment",
        "gst_filing",
        "whatsapp_alert_batch",
    }
)


def is_high_risk(action_type: str) -> bool:
    return action_type in HIGH_RISK_ACTIONS
