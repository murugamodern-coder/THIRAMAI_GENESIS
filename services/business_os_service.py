"""
Multi-tenant Business OS helpers: operational expense listing, agro subsidies, tasks, daily P&L rollups.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.database import get_session_factory
from core.db.models import AgroSubsidyCase, Bill, BusinessTask, Invoice, OperationalExpense


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _month_start_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def list_operational_expenses_sync(
    *,
    organization_id: int,
    limit: int = 200,
    from_date: date | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 500))
    with factory() as session:
        q = select(OperationalExpense).where(OperationalExpense.organization_id == oid)
        if from_date is not None:
            q = q.where(OperationalExpense.expense_date >= from_date)
        q = q.order_by(OperationalExpense.id.desc()).limit(lim)
        rows = list(session.scalars(q).all())
        items = [
            {
                "id": int(r.id),
                "expense_date": r.expense_date.isoformat() if r.expense_date else None,
                "category": r.category,
                "amount_inr": float(r.amount_inr),
                "description": r.description,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    return {"ok": True, "expenses": items}


def _sum_bills_period(
    session: Session, *, organization_id: int, start: datetime, end: datetime
) -> Decimal:
    v = session.execute(
        select(func.coalesce(func.sum(Bill.total_amount), 0)).where(
            Bill.organization_id == int(organization_id),
            Bill.created_at >= start,
            Bill.created_at < end,
        )
    ).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _sum_invoices_by_invoice_date(
    session: Session, *, organization_id: int, start_d: date, end_d: date
) -> Decimal:
    """Sum structured invoice grand totals where invoice_date falls in [start_d, end_d]."""
    v = session.execute(
        select(func.coalesce(func.sum(Invoice.grand_total_inr), 0)).where(
            Invoice.organization_id == int(organization_id),
            Invoice.invoice_date.isnot(None),
            Invoice.invoice_date >= start_d,
            Invoice.invoice_date <= end_d,
        )
    ).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _sum_opex_period(
    session: Session, *, organization_id: int, start_d: date, end_d: date
) -> Decimal:
    v = session.execute(
        select(func.coalesce(func.sum(OperationalExpense.amount_inr), 0)).where(
            OperationalExpense.organization_id == int(organization_id),
            OperationalExpense.expense_date >= start_d,
            OperationalExpense.expense_date <= end_d,
        )
    ).scalar_one()
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def daily_pl_summary_sync(*, organization_id: int) -> dict[str, Any]:
    """
    Today's sales (bills created today UTC + invoices dated today),
    today's opex, MTD same. Net = sales - opex (same-day / same-period; not COGS).
    """
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}

    now = _utc_now()
    today_date = now.date()
    day_start, day_end = _day_bounds_utc(today_date)
    month_start = _month_start_utc(now)

    with factory() as session:
        bills_today = _sum_bills_period(session, organization_id=oid, start=day_start, end=day_end)
        inv_today = _sum_invoices_by_invoice_date(
            session, organization_id=oid, start_d=today_date, end_d=today_date
        )
        sales_today = (bills_today + inv_today).quantize(Decimal("0.01"))

        bills_mtd = _sum_bills_period(session, organization_id=oid, start=month_start, end=now + timedelta(microseconds=1))
        inv_mtd = _sum_invoices_by_invoice_date(
            session,
            organization_id=oid,
            start_d=month_start.date(),
            end_d=today_date,
        )
        sales_mtd = (bills_mtd + inv_mtd).quantize(Decimal("0.01"))

        opex_today = _sum_opex_period(session, organization_id=oid, start_d=today_date, end_d=today_date)
        opex_mtd = _sum_opex_period(
            session, organization_id=oid, start_d=month_start.date(), end_d=today_date
        )

    def _f(d: Decimal) -> float:
        return float(d)

    return {
        "ok": True,
        "as_of_utc": now.isoformat(),
        "today": {
            "sales_inr": _f(sales_today),
            "bills_inr": _f(bills_today),
            "invoices_inr": _f(inv_today),
            "expenses_inr": _f(opex_today),
            "net_inr": _f(sales_today - opex_today),
        },
        "month_to_date": {
            "sales_inr": _f(sales_mtd),
            "expenses_inr": _f(opex_mtd),
            "net_inr": _f(sales_mtd - opex_mtd),
        },
    }


def _serialize_subsidy(r: AgroSubsidyCase) -> dict[str, Any]:
    return {
        "id": int(r.id),
        "farmer_name": r.farmer_name,
        "village": r.village or "",
        "survey_number": r.survey_number or "",
        "scheme_name": r.scheme_name,
        "application_status": r.application_status,
        "subsidy_pending_inr": float(r.subsidy_pending_inr),
        "subsidy_received_inr": float(r.subsidy_received_inr),
        "follow_up_date": r.follow_up_date.isoformat() if r.follow_up_date else None,
        "notes": r.notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def list_subsidy_cases_sync(*, organization_id: int, limit: int = 200) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 500))
    with factory() as session:
        rows = list(
            session.scalars(
                select(AgroSubsidyCase)
                .where(AgroSubsidyCase.organization_id == oid)
                .order_by(AgroSubsidyCase.id.desc())
                .limit(lim)
            ).all()
        )
    return {"ok": True, "cases": [_serialize_subsidy(r) for r in rows]}


def create_subsidy_case_sync(
    *,
    organization_id: int,
    farmer_name: str,
    village: str = "",
    survey_number: str = "",
    scheme_name: str,
    application_status: str = "draft",
    subsidy_pending_inr: Decimal | float = 0,
    subsidy_received_inr: Decimal | float = 0,
    follow_up_date: date | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    fn = (farmer_name or "").strip()
    sn = (scheme_name or "").strip()
    if not fn or not sn:
        return {"ok": False, "error": "farmer_name and scheme_name required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    try:
        pend = Decimal(str(subsidy_pending_inr)).quantize(Decimal("0.01"))
        recv = Decimal(str(subsidy_received_inr)).quantize(Decimal("0.01"))
    except Exception:
        return {"ok": False, "error": "invalid subsidy amounts"}
    with factory() as session:
        with session.begin():
            row = AgroSubsidyCase(
                organization_id=oid,
                farmer_name=fn,
                village=(village or "").strip(),
                survey_number=(survey_number or "").strip(),
                scheme_name=sn,
                application_status=(application_status or "draft").strip()[:64],
                subsidy_pending_inr=pend,
                subsidy_received_inr=recv,
                follow_up_date=follow_up_date,
                notes=(notes or "").strip()[:4000] or None,
            )
            session.add(row)
            session.flush()
            cid = int(row.id)
    return {"ok": True, "id": cid}


def update_subsidy_case_sync(
    *,
    organization_id: int,
    case_id: int,
    **fields: Any,
) -> dict[str, Any]:
    oid = int(organization_id)
    cid = int(case_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        with session.begin():
            row = session.get(AgroSubsidyCase, cid)
            if row is None or int(row.organization_id) != oid:
                return {"ok": False, "error": "case not found"}
            if "farmer_name" in fields and fields["farmer_name"] is not None:
                row.farmer_name = str(fields["farmer_name"]).strip()[:2000]
            if "village" in fields:
                row.village = str(fields["village"] or "").strip()[:500]
            if "survey_number" in fields:
                row.survey_number = str(fields["survey_number"] or "").strip()[:500]
            if "scheme_name" in fields and fields["scheme_name"] is not None:
                row.scheme_name = str(fields["scheme_name"]).strip()[:2000]
            if "application_status" in fields and fields["application_status"] is not None:
                row.application_status = str(fields["application_status"]).strip()[:64]
            for key in ("subsidy_pending_inr", "subsidy_received_inr"):
                if key in fields and fields[key] is not None:
                    try:
                        val = Decimal(str(fields[key])).quantize(Decimal("0.01"))
                    except Exception:
                        return {"ok": False, "error": f"invalid {key}"}
                    setattr(row, key, val)
            if "follow_up_date" in fields:
                row.follow_up_date = fields["follow_up_date"]
            if "notes" in fields:
                row.notes = (str(fields["notes"] or "").strip()[:4000] or None)
    return {"ok": True}


def _serialize_task(r: BusinessTask) -> dict[str, Any]:
    return {
        "id": int(r.id),
        "title": r.title,
        "owner_name": r.owner_name or "",
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "status": r.status,
        "task_type": r.task_type,
        "checklist_json": r.checklist_json if isinstance(r.checklist_json, list) else [],
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def list_business_tasks_sync(*, organization_id: int, limit: int = 200) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    lim = max(1, min(int(limit), 500))
    with factory() as session:
        rows = list(
            session.scalars(
                select(BusinessTask)
                .where(BusinessTask.organization_id == oid)
                .order_by(BusinessTask.id.desc())
                .limit(lim)
            ).all()
        )
    return {"ok": True, "tasks": [_serialize_task(r) for r in rows]}


def create_business_task_sync(
    *,
    organization_id: int,
    title: str,
    owner_name: str = "",
    due_at: datetime | None = None,
    task_type: str = "general",
    checklist_json: list[Any] | None = None,
) -> dict[str, Any]:
    oid = int(organization_id)
    t = (title or "").strip()
    if not t:
        return {"ok": False, "error": "title required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    chk = checklist_json if isinstance(checklist_json, list) else []
    with factory() as session:
        with session.begin():
            row = BusinessTask(
                organization_id=oid,
                title=t[:2000],
                owner_name=(owner_name or "").strip()[:500],
                due_at=due_at,
                status="pending",
                task_type=(task_type or "general").strip()[:64],
                checklist_json=chk,
            )
            session.add(row)
            session.flush()
            tid = int(row.id)
    return {"ok": True, "id": tid}


def update_business_task_sync(
    *,
    organization_id: int,
    task_id: int,
    **fields: Any,
) -> dict[str, Any]:
    oid = int(organization_id)
    tid = int(task_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        with session.begin():
            row = session.get(BusinessTask, tid)
            if row is None or int(row.organization_id) != oid:
                return {"ok": False, "error": "task not found"}
            if "title" in fields and fields["title"] is not None:
                row.title = str(fields["title"]).strip()[:2000]
            if "owner_name" in fields:
                row.owner_name = str(fields["owner_name"] or "").strip()[:500]
            if "due_at" in fields:
                row.due_at = fields["due_at"]
            if "status" in fields and fields["status"] is not None:
                row.status = str(fields["status"]).strip()[:32]
            if "task_type" in fields and fields["task_type"] is not None:
                row.task_type = str(fields["task_type"]).strip()[:64]
            if "checklist_json" in fields and fields["checklist_json"] is not None:
                cj = fields["checklist_json"]
                row.checklist_json = cj if isinstance(cj, list) else []
    return {"ok": True}
