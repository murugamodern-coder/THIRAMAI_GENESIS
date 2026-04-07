"""
ERP finance ledger: append-only ``ledger_transactions`` rows + optional standalone recording.

Keeps ``services.financial_service`` (TSI / debt accrual) separate — this module is the **journal**.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import LedgerTransaction
from services import audit_log as system_audit


def insert_ledger_row(
    session: Session,
    *,
    organization_id: int,
    user_id: int | None,
    entry_type: str,
    amount_inr: Decimal,
    category: str = "general",
    reference: str = "",
    extra: dict[str, Any] | None = None,
) -> int:
    """Add a ledger row within an existing transaction. Returns new id."""
    row = LedgerTransaction(
        organization_id=int(organization_id),
        user_id=int(user_id) if user_id is not None and int(user_id) > 0 else None,
        entry_type=(entry_type or "adjustment").strip()[:32] or "adjustment",
        amount_inr=amount_inr,
        category=(category or "general").strip()[:64] or "general",
        reference=(reference or "")[:4000],
        extra=dict(extra or {}),
    )
    session.add(row)
    session.flush()
    return int(row.id)


def record_transaction_sync(
    *,
    organization_id: int,
    amount_inr: float | Decimal,
    entry_type: str = "adjustment",
    category: str = "general",
    reference: str = "",
    user_id: int | None = None,
    extra: dict[str, Any] | None = None,
    audit: bool = True,
) -> dict[str, Any]:
    """
    Standalone journal entry + system audit (``ACTION_FINANCIAL_EXECUTION``).

    ``amount_inr`` is stored as given (positive for inflows such as revenue postings).
    """
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    amt = Decimal(str(amount_inr))
    oid = int(organization_id)
    with factory() as session:
        with session.begin():
            lid = insert_ledger_row(
                session,
                organization_id=oid,
                user_id=user_id,
                entry_type=entry_type,
                amount_inr=amt,
                category=category,
                reference=reference,
                extra=extra,
            )
    if audit:
        system_audit.record_system_audit(
            action=system_audit.ACTION_FINANCIAL_EXECUTION,
            outcome="success",
            organization_id=oid,
            user_id=user_id if user_id and int(user_id) > 0 else None,
            resource_type="ledger_transaction",
            metadata={
                "ledger_id": lid,
                "entry_type": (entry_type or "")[:32],
                "amount_inr": float(amt),
                "category": (category or "")[:64],
                "reference": (reference or "")[:128],
            },
        )
    return {"ok": True, "ledger_transaction_id": lid, "organization_id": oid}
