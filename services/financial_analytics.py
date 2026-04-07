"""
Empire financial aggregates: revenue (invoices), outstanding debt principal, production labor costs.

All queries are scoped to a single ``organization_id`` (tenant boundary).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import Asset, Debt, Invoice, ProductionLog


def aggregate_empire_financial_summary_session(session: Session, *, organization_id: int) -> dict[str, Any]:
    """
    Aggregate for one organization only:

    - **total_revenue_inr:** sum of ``invoices.grand_total_inr``. If that sum is zero and the
      ``invoices`` table has no rows (or only zeros), fall back to sum of ``assets.valuation``
      where ``category`` is ``invoice`` (legacy rows from master_index migration).
    - **pending_debts_principal_inr:** sum of ``debts.principal`` for the org (no paid flag in schema;
      treated as total outstanding book).
    - **production_costs_inr:** sum of ``production_logs.labor_cost`` joined through ``assets``
      filtered by ``organization_id`` (only INR cost field on logs).
    """
    oid = int(organization_id)

    invoice_row_count = int(
        session.scalar(select(func.count()).select_from(Invoice).where(Invoice.organization_id == oid)) or 0
    )
    inv_rev = session.scalar(
        select(func.coalesce(func.sum(Invoice.grand_total_inr), 0)).where(Invoice.organization_id == oid)
    )
    inv_rev = inv_rev if inv_rev is not None else Decimal("0")

    if invoice_row_count == 0:
        asset_rev = session.scalar(
            select(func.coalesce(func.sum(Asset.valuation), 0)).where(
                Asset.organization_id == oid,
                func.lower(Asset.category) == "invoice",
            )
        )
        asset_rev = asset_rev if asset_rev is not None else Decimal("0")
        total_revenue = asset_rev
        revenue_note = (
            "No rows in `invoices`; revenue uses `assets.valuation` where category is `invoice` "
            "(legacy master_index / migration path). Populate `invoices` for ledger-grade revenue."
        )
    else:
        total_revenue = inv_rev
        revenue_note = "Sum of `invoices.grand_total_inr` for this organization."

    pending_debts = session.scalar(
        select(func.coalesce(func.sum(Debt.principal), 0)).where(Debt.organization_id == oid)
    )
    pending_debts = pending_debts if pending_debts is not None else Decimal("0")

    labor_sum = session.scalar(
        select(func.coalesce(func.sum(ProductionLog.labor_cost), 0))
        .select_from(ProductionLog)
        .join(Asset, ProductionLog.asset_id == Asset.id)
        .where(Asset.organization_id == oid)
    )
    labor_sum = labor_sum if labor_sum is not None else Decimal("0")

    log_count = session.scalar(
        select(func.count())
        .select_from(ProductionLog)
        .join(Asset, ProductionLog.asset_id == Asset.id)
        .where(Asset.organization_id == oid)
    ) or 0

    return {
        "organization_id": oid,
        "total_revenue_inr": float(total_revenue.quantize(Decimal("0.01"))),
        "revenue_note": revenue_note,
        "pending_debts_principal_inr": float(pending_debts.quantize(Decimal("0.01"))),
        "pending_debts_note": (
            "Sum of `debts.principal` for this organization. There is no paid/settled flag; "
            "the entire book is treated as outstanding."
        ),
        "production_costs_inr": float(labor_sum.quantize(Decimal("0.01"))),
        "production_costs_note": (
            "Sum of `production_logs.labor_cost` for logs whose asset belongs to this organization."
        ),
        "production_log_row_count": int(log_count),
    }


def aggregate_empire_financial_summary(organization_id: int) -> dict[str, Any]:
    """Open a DB session, aggregate, commit (read-only). Raises ``RuntimeError`` if DB is unavailable."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not configured")
    with factory() as session:
        return aggregate_empire_financial_summary_session(session, organization_id=int(organization_id))
