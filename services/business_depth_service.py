"""
Business OS mutations (departments, staff, attendance, opex) — tenant-scoped by ``organization_id``.

Callers (HTTP routes) must pass the JWT **active** org id; this module does not resolve membership.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import AttendanceLog, Department, OperationalExpense, StaffProfile


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def set_department_lead(
    *,
    organization_id: int,
    department_id: int,
    lead_user_id: int | None,
) -> tuple[bool, str]:
    oid = int(organization_id)
    did = int(department_id)
    factory = _factory()
    if factory is None:
        return False, "database not configured"
    with factory() as session:
        with session.begin():
            row = session.get(Department, did)
            if row is None or int(row.organization_id) != oid:
                return False, "department not found"
            row.lead_user_id = int(lead_user_id) if lead_user_id is not None and int(lead_user_id) > 0 else None
    return True, "ok"


def upsert_staff_profile(
    *,
    organization_id: int,
    user_id: int,
    department_id: int | None = None,
    basic_salary: Decimal | float | str = Decimal("0"),
    joining_date: date | None = None,
    status: str = "active",
) -> tuple[bool, str, int | None]:
    oid = int(organization_id)
    uid = int(user_id)
    if uid <= 0:
        return False, "invalid user", None
    try:
        sal = Decimal(str(basic_salary)).quantize(Decimal("0.01"))
    except Exception:
        return False, "invalid salary", None
    st = (status or "active").strip().lower()[:32]
    jd = joining_date or datetime.now(timezone.utc).date()
    dept_id = int(department_id) if department_id is not None and int(department_id) > 0 else None

    factory = _factory()
    if factory is None:
        return False, "database not configured", None

    with factory() as session:
        with session.begin():
            if dept_id is not None:
                d = session.get(Department, dept_id)
                if d is None or int(d.organization_id) != oid:
                    return False, "department not found", None
            existing = session.execute(
                select(StaffProfile).where(StaffProfile.user_id == uid, StaffProfile.organization_id == oid).limit(1)
            ).scalar_one_or_none()
            if existing:
                existing.department_id = dept_id
                existing.basic_salary = sal
                existing.joining_date = jd
                existing.status = st
                return True, "ok", int(existing.id)
            row = StaffProfile(
                user_id=uid,
                organization_id=oid,
                department_id=dept_id,
                basic_salary=sal,
                joining_date=jd,
                status=st,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)


def attendance_check_in(
    *,
    organization_id: int,
    staff_profile_id: int,
    check_in: datetime | None = None,
    status: str = "present",
) -> tuple[bool, str, int | None]:
    oid = int(organization_id)
    sid = int(staff_profile_id)
    factory = _factory()
    if factory is None:
        return False, "database not configured", None
    when = check_in if check_in is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    st = (status or "present").strip().lower()[:32]

    with factory() as session:
        with session.begin():
            sp = session.get(StaffProfile, sid)
            if sp is None or int(sp.organization_id) != oid:
                return False, "staff profile not found", None
            log = AttendanceLog(staff_id=sid, check_in=when, check_out=None, status=st)
            session.add(log)
            session.flush()
            return True, "ok", int(log.id)


def attendance_check_out(
    *,
    organization_id: int,
    attendance_log_id: int | None = None,
    staff_profile_id: int | None = None,
    check_out: datetime | None = None,
) -> tuple[bool, str]:
    oid = int(organization_id)
    factory = _factory()
    if factory is None:
        return False, "database not configured"
    when = check_out if check_out is not None else datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    with factory() as session:
        with session.begin():
            log: AttendanceLog | None = None
            if attendance_log_id is not None and int(attendance_log_id) > 0:
                log = session.get(AttendanceLog, int(attendance_log_id))
            elif staff_profile_id is not None and int(staff_profile_id) > 0:
                sp = session.get(StaffProfile, int(staff_profile_id))
                if sp is None or int(sp.organization_id) != oid:
                    return False, "staff profile not found"
                log = session.execute(
                    select(AttendanceLog)
                    .where(
                        AttendanceLog.staff_id == int(staff_profile_id),
                        AttendanceLog.check_out.is_(None),
                    )
                    .order_by(AttendanceLog.check_in.desc())
                    .limit(1)
                ).scalar_one_or_none()
            else:
                return False, "attendance_log_id or staff_profile_id required"

            if log is None:
                return False, "attendance log not found"
            sp = session.get(StaffProfile, int(log.staff_id))
            if sp is None or int(sp.organization_id) != oid:
                return False, "attendance log not found"
            if log.check_out is not None:
                return False, "already checked out"
            log.check_out = when
    return True, "ok"


def record_operational_expense(
    *,
    organization_id: int,
    expense_date: date,
    category: str,
    amount_inr: Decimal | float | str,
    description: str | None = None,
) -> tuple[bool, str, int | None]:
    oid = int(organization_id)
    try:
        amt = Decimal(str(amount_inr)).quantize(Decimal("0.01"))
    except Exception:
        return False, "invalid amount", None
    if amt < 0:
        return False, "amount must be non-negative", None
    cat = (category or "general").strip()[:64] or "general"
    factory = _factory()
    if factory is None:
        return False, "database not configured", None
    with factory() as session:
        with session.begin():
            row = OperationalExpense(
                organization_id=oid,
                expense_date=expense_date,
                category=cat,
                amount_inr=amt,
                description=(description or "").strip()[:2000] or None,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)
