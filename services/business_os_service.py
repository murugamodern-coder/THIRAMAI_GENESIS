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
from core.db.models import AgroSubsidyCase, Bill, BusinessTask, Invoice, OperationalExpense, OrganizationLiquidity


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _month_start_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _prev_month_start_utc(now: datetime) -> datetime:
    if now.month == 1:
        return datetime(now.year - 1, 12, 1, tzinfo=timezone.utc)
    return datetime(now.year, now.month - 1, 1, tzinfo=timezone.utc)


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
    prev_month_start = _prev_month_start_utc(now)
    prev_month_end_date = month_start.date() - timedelta(days=1)

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

        bills_prev = _sum_bills_period(session, organization_id=oid, start=prev_month_start, end=month_start)
        inv_prev = _sum_invoices_by_invoice_date(
            session,
            organization_id=oid,
            start_d=prev_month_start.date(),
            end_d=prev_month_end_date,
        )
        sales_prev = (bills_prev + inv_prev).quantize(Decimal("0.01"))
        opex_prev = _sum_opex_period(
            session, organization_id=oid, start_d=prev_month_start.date(), end_d=prev_month_end_date
        )

        liq = session.get(OrganizationLiquidity, oid)
        cash_bal = float(liq.cash_inr) if liq is not None else 0.0
        bank_bal = float(liq.bank_inr) if liq is not None else 0.0

    def _f(d: Decimal) -> float:
        return float(d)

    net_prev = sales_prev - opex_prev
    net_mtd = sales_mtd - opex_mtd

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
            "net_inr": _f(net_mtd),
        },
        "previous_calendar_month": {
            "label": f"{prev_month_start.year}-{prev_month_start.month:02d}",
            "sales_inr": _f(sales_prev),
            "expenses_inr": _f(opex_prev),
            "net_inr": _f(net_prev),
            "net_vs_current_mtd_inr": _f(net_mtd - net_prev),
        },
        "liquidity_inr": {
            "cash": cash_bal,
            "bank": bank_bal,
            "total": cash_bal + bank_bal,
        },
    }


def _serialize_subsidy(r: AgroSubsidyCase) -> dict[str, Any]:
    return {
        "id": int(r.id),
        "farmer_name": r.farmer_name,
        "village": r.village or "",
        "survey_number": r.survey_number or "",
        "farmer_phone": getattr(r, "farmer_phone", None),
        "land_acres": float(r.land_acres) if getattr(r, "land_acres", None) is not None else None,
        "scheme_name": r.scheme_name,
        "application_status": r.application_status,
        "subsidy_applied_inr": float(getattr(r, "subsidy_applied_inr", 0) or 0),
        "subsidy_approved_inr": float(getattr(r, "subsidy_approved_inr", 0) or 0),
        "subsidy_pending_inr": float(r.subsidy_pending_inr),
        "subsidy_received_inr": float(r.subsidy_received_inr),
        "commission_earned_inr": float(getattr(r, "commission_earned_inr", 0) or 0),
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
    farmer_phone: str | None = None,
    land_acres: Decimal | float | None = None,
    scheme_name: str,
    application_status: str = "draft",
    subsidy_applied_inr: Decimal | float = 0,
    subsidy_approved_inr: Decimal | float = 0,
    subsidy_pending_inr: Decimal | float = 0,
    subsidy_received_inr: Decimal | float = 0,
    commission_earned_inr: Decimal | float = 0,
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
        appl = Decimal(str(subsidy_applied_inr)).quantize(Decimal("0.01"))
        appr = Decimal(str(subsidy_approved_inr)).quantize(Decimal("0.01"))
        pend = Decimal(str(subsidy_pending_inr)).quantize(Decimal("0.01"))
        recv = Decimal(str(subsidy_received_inr)).quantize(Decimal("0.01"))
        comm = Decimal(str(commission_earned_inr)).quantize(Decimal("0.01"))
        acres = (
            Decimal(str(land_acres)).quantize(Decimal("0.0001"))
            if land_acres is not None
            else None
        )
    except Exception:
        return {"ok": False, "error": "invalid subsidy amounts"}
    with factory() as session:
        with session.begin():
            row = AgroSubsidyCase(
                organization_id=oid,
                farmer_name=fn,
                village=(village or "").strip(),
                survey_number=(survey_number or "").strip(),
                farmer_phone=(farmer_phone or "").strip()[:32] or None,
                land_acres=acres,
                scheme_name=sn,
                application_status=(application_status or "draft").strip()[:64],
                subsidy_applied_inr=appl,
                subsidy_approved_inr=appr,
                subsidy_pending_inr=pend,
                subsidy_received_inr=recv,
                commission_earned_inr=comm,
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
            if "farmer_phone" in fields:
                row.farmer_phone = (str(fields["farmer_phone"] or "").strip()[:32] or None)
            if "land_acres" in fields and fields["land_acres"] is not None:
                try:
                    row.land_acres = Decimal(str(fields["land_acres"])).quantize(Decimal("0.0001"))
                except Exception:
                    return {"ok": False, "error": "invalid land_acres"}
            for key in (
                "subsidy_applied_inr",
                "subsidy_approved_inr",
                "subsidy_pending_inr",
                "subsidy_received_inr",
                "commission_earned_inr",
            ):
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


def get_liquidity_sync(*, organization_id: int) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        row = session.get(OrganizationLiquidity, oid)
        if row is None:
            return {"ok": True, "cash_inr": 0.0, "bank_inr": 0.0, "updated_at": None}
        return {
            "ok": True,
            "cash_inr": float(row.cash_inr),
            "bank_inr": float(row.bank_inr),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


def upsert_liquidity_sync(
    *,
    organization_id: int,
    cash_inr: Decimal | float,
    bank_inr: Decimal | float,
) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0:
        return {"ok": False, "error": "organization_id required"}
    try:
        c = Decimal(str(cash_inr)).quantize(Decimal("0.01"))
        b = Decimal(str(bank_inr)).quantize(Decimal("0.01"))
    except Exception:
        return {"ok": False, "error": "invalid amounts"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    with factory() as session:
        with session.begin():
            row = session.get(OrganizationLiquidity, oid)
            if row is None:
                row = OrganizationLiquidity(organization_id=oid, cash_inr=c, bank_inr=b)
                session.add(row)
            else:
                row.cash_inr = c
                row.bank_inr = b
    return {"ok": True}


def monthly_expense_report_sync(*, organization_id: int, year: int, month: int) -> dict[str, Any]:
    oid = int(organization_id)
    if oid <= 0 or month < 1 or month > 12:
        return {"ok": False, "error": "invalid organization or month"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL is not configured"}
    start_d = date(year, month, 1)
    if month == 12:
        end_d = date(year, 12, 31)
    else:
        end_d = date(year, month + 1, 1) - timedelta(days=1)
    with factory() as session:
        rows = list(
            session.scalars(
                select(OperationalExpense)
                .where(
                    OperationalExpense.organization_id == oid,
                    OperationalExpense.expense_date >= start_d,
                    OperationalExpense.expense_date <= end_d,
                )
                .order_by(OperationalExpense.expense_date, OperationalExpense.id)
            ).all()
        )
    by_cat: dict[str, Decimal] = {}
    total = Decimal("0")
    for r in rows:
        cat = (r.category or "other").strip()
        amt = Decimal(str(r.amount_inr or 0)).quantize(Decimal("0.01"))
        by_cat[cat] = by_cat.get(cat, Decimal("0")) + amt
        total += amt
    return {
        "ok": True,
        "year": year,
        "month": month,
        "period_start": start_d.isoformat(),
        "period_end": end_d.isoformat(),
        "total_inr": float(total),
        "by_category": {k: float(v) for k, v in sorted(by_cat.items())},
        "line_count": len(rows),
    }
