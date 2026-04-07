"""Financial summaries, TSI-style payloads, and DB-backed interest accrual."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import Debt


def financial_performance_summary() -> dict[str, Any]:
    """
    Host-wide TSI summary (all index rows + **all** debts for interest accrual).

    **Not tenant-scoped** — for smoke tests / CLI only; HTTP APIs must use
    ``financial_performance_summary_for_organization``.
    """
    import asset_portal

    summary = asset_portal.financial_performance_summary()
    accrual = daily_interest_accrual_dashboard()
    if accrual.get("ok"):
        summary["daily_interest_accrual"] = accrual
    return summary


def financial_performance_summary_for_organization(organization_id: int) -> dict[str, Any]:
    """Vault / index financial signals scoped to the JWT tenant."""
    import asset_portal

    summary = asset_portal.financial_performance_summary_for_organization(int(organization_id))
    accrual = daily_interest_accrual_dashboard_for_organization(int(organization_id))
    if accrual.get("ok"):
        summary["daily_interest_accrual"] = accrual
    return summary


def daily_interest_accrual_dashboard() -> dict[str, Any]:
    """
    Simple daily interest accrual: sum over debts of principal * (annual_rate/100) / 365.
    Rates stored as annual percentages (e.g. 26.5 for 26.5% p.a.).
    """
    as_of = datetime.now(timezone.utc).isoformat()
    factory = get_session_factory()
    if factory is None:
        return {
            "ok": False,
            "reason": "DATABASE_URL not configured",
            "as_of_utc": as_of,
            "total_principal_inr": 0.0,
            "daily_interest_inr_total": 0.0,
            "debts": [],
        }

    daily_total = Decimal("0")
    principal_total = Decimal("0")
    rows_out: list[dict[str, Any]] = []

    try:
        with factory() as session:
            debts = session.execute(select(Debt).order_by(Debt.id)).scalars().all()
            for d in debts:
                p = d.principal or Decimal("0")
                principal_total += p
                r_annual = d.interest_rate
                if r_annual is None:
                    daily = Decimal("0")
                else:
                    daily = (p * (r_annual / Decimal("100"))) / Decimal("365")
                daily_total += daily
                rows_out.append(
                    {
                        "id": d.id,
                        "lender_name": d.lender_name,
                        "principal_inr": float(p),
                        "interest_rate_annual_pct": float(r_annual) if r_annual is not None else None,
                        "daily_interest_inr": float(daily.quantize(Decimal("0.01"))),
                        "category": d.category_enum.value,
                    }
                )
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "as_of_utc": as_of,
            "total_principal_inr": 0.0,
            "daily_interest_inr_total": 0.0,
            "debts": [],
        }

    return {
        "ok": True,
        "as_of_utc": as_of,
        "total_principal_inr": float(principal_total),
        "daily_interest_inr_total": float(daily_total.quantize(Decimal("0.01"))),
        "debts": rows_out,
        "note": "Accrual uses ACT/365 simple daily interest on each debt line.",
    }


def daily_interest_accrual_dashboard_for_organization(organization_id: int) -> dict[str, Any]:
    """Like ``daily_interest_accrual_dashboard`` but only debts for ``organization_id``."""
    as_of = datetime.now(timezone.utc).isoformat()
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return {
            "ok": False,
            "reason": "DATABASE_URL not configured",
            "as_of_utc": as_of,
            "organization_id": oid,
            "total_principal_inr": 0.0,
            "daily_interest_inr_total": 0.0,
            "debts": [],
        }

    daily_total = Decimal("0")
    principal_total = Decimal("0")
    rows_out: list[dict[str, Any]] = []

    try:
        with factory() as session:
            debts = session.execute(
                select(Debt).where(Debt.organization_id == oid).order_by(Debt.id)
            ).scalars().all()
            for d in debts:
                p = d.principal or Decimal("0")
                principal_total += p
                r_annual = d.interest_rate
                if r_annual is None:
                    daily = Decimal("0")
                else:
                    daily = (p * (r_annual / Decimal("100"))) / Decimal("365")
                daily_total += daily
                rows_out.append(
                    {
                        "id": d.id,
                        "lender_name": d.lender_name,
                        "principal_inr": float(p),
                        "interest_rate_annual_pct": float(r_annual) if r_annual is not None else None,
                        "daily_interest_inr": float(daily.quantize(Decimal("0.01"))),
                        "category": d.category_enum.value,
                    }
                )
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "as_of_utc": as_of,
            "organization_id": oid,
            "total_principal_inr": 0.0,
            "daily_interest_inr_total": 0.0,
            "debts": [],
        }

    return {
        "ok": True,
        "as_of_utc": as_of,
        "organization_id": oid,
        "total_principal_inr": float(principal_total),
        "daily_interest_inr_total": float(daily_total.quantize(Decimal("0.01"))),
        "debts": rows_out,
        "note": "Accrual uses ACT/365 simple daily interest on each debt line (tenant-scoped).",
    }
