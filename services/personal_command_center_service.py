"""
Personal Command Center — morning brief, finance, vitals, medicine, doctor visits (DB + optional Fernet).

Uses ``life_os_service.unlock_fernet`` when ``X-Personal-Vault-Passphrase`` is supplied for encrypted fields.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from core.database import get_session_factory
from core.db.models import (
    DoctorVisit,
    MedicineTracker,
    PersonalBudget,
    PersonalExpense,
    PersonalLoan,
    PersonalMission,
    ResearchProject,
    VitalRecord,
)
from core.personal_ai_engine import generate_daily_guidance
from services import life_os_service
from services.personal_crypto import encrypt_utf8
from services.personal_os_aggregate import MISSION_OPEN_STATUSES

_PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}


def _mission_priority_key(m: PersonalMission) -> tuple[int, datetime]:
    raw = (getattr(m, "priority", None) or "P2").strip().upper()
    if raw not in _PRIORITY_ORDER:
        raw = "P2"
    dl = m.deadline if m.deadline is not None else datetime(9999, 12, 31, tzinfo=timezone.utc)
    return (_PRIORITY_ORDER[raw], dl)


def _factory():
    return get_session_factory()


def _maybe_encrypt(*, plain: str | None, fernet: Fernet | None) -> tuple[bytes | None, bool]:
    if not plain or not str(plain).strip():
        return None, False
    if fernet is None:
        return None, False
    return encrypt_utf8(fernet, plain.strip()), True


def fetch_open_meteo_current(*, latitude: float, longitude: float) -> dict[str, Any] | None:
    """Free Open-Meteo current weather (no API key)."""
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}&current=temperature_2m,weather_code"
        )
        with httpx.Client(timeout=8.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
        cur = data.get("current") or {}
        return {
            "temperature_c": cur.get("temperature_2m"),
            "weather_code": cur.get("weather_code"),
            "latitude": latitude,
            "longitude": longitude,
        }
    except Exception:
        return None


def build_morning_brief_sync(
    *,
    user_id: int,
    organization_id: int,
    fernet: Fernet | None = None,
) -> dict[str, Any]:
    uid = int(user_id)
    now = datetime.now(timezone.utc)
    today = now.date()
    yesterday = today - timedelta(days=1)

    lat = float(os.getenv("PERSONAL_OS_WEATHER_LAT") or "0")
    lon = float(os.getenv("PERSONAL_OS_WEATHER_LON") or "0")
    weather = None
    if lat and lon and abs(lat) <= 90 and abs(lon) <= 180:
        weather = fetch_open_meteo_current(latitude=lat, longitude=lon)

    priorities: list[dict[str, Any]] = []
    financial: dict[str, Any] = {"currency": "INR", "spent_today": "0", "spent_month": "0", "upcoming_emis": []}
    health_score: dict[str, Any] = {"score": None, "hint": "Log vitals to unlock a score."}
    ai_insight: str = ""

    factory = _factory()
    if factory is None:
        return {
            "as_of_utc": now.isoformat(),
            "date": today.isoformat(),
            "weather": weather,
            "priorities": [],
            "meetings": [],
            "pending_decisions": [],
            "financial_snapshot": financial,
            "health_score": health_score,
            "ai_insight": "Database not configured.",
        }

    with factory() as session:
        stmt = select(PersonalMission).where(
            PersonalMission.user_id == uid,
            PersonalMission.status.in_(tuple(MISSION_OPEN_STATUSES)),
        )
        missions = list(session.execute(stmt).scalars().all())
        missions.sort(key=_mission_priority_key)
        for m in missions[:3]:
            priorities.append(
                {
                    "id": int(m.id),
                    "title": m.title,
                    "priority": getattr(m, "priority", None) or "P2",
                    "deadline": m.deadline.isoformat() if m.deadline else None,
                }
            )

        day_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        month_start = day_start.replace(day=1)

        spent_today = session.execute(
            select(func.coalesce(func.sum(PersonalExpense.amount), 0)).where(
                PersonalExpense.user_id == uid,
                PersonalExpense.spent_at >= day_start,
                PersonalExpense.spent_at < day_end,
            )
        ).scalar()
        spent_month = session.execute(
            select(func.coalesce(func.sum(PersonalExpense.amount), 0)).where(
                PersonalExpense.user_id == uid,
                PersonalExpense.spent_at >= month_start,
                PersonalExpense.spent_at < day_end,
            )
        ).scalar()
        financial["spent_today"] = str(spent_today or Decimal("0"))
        financial["spent_month"] = str(spent_month or Decimal("0"))

        emis = session.execute(
            select(PersonalLoan)
            .where(
                PersonalLoan.user_id == uid,
                PersonalLoan.is_closed.is_(False),
                PersonalLoan.next_due_date.isnot(None),
            )
            .order_by(PersonalLoan.next_due_date.asc())
            .limit(5)
        ).scalars().all()
        financial["upcoming_emis"] = [
            {
                "id": int(x.id),
                "name": x.display_name,
                "due": x.next_due_date.isoformat() if x.next_due_date else None,
                "emi": str(x.emi_amount) if x.emi_amount is not None else None,
            }
            for x in emis
        ]

        v_y = session.execute(
            select(VitalRecord)
            .where(
                VitalRecord.user_id == uid,
                VitalRecord.recorded_at
                >= datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=timezone.utc),
            )
            .order_by(VitalRecord.recorded_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if v_y is not None:
            score = 50
            if v_y.sleep_hours is not None:
                sh = float(v_y.sleep_hours)
                score += min(25, max(0, int((sh - 5) * 5)))
            if v_y.stress_1_10 is not None:
                score += max(0, 25 - int(v_y.stress_1_10) * 2)
            health_score = {
                "score": max(0, min(100, score)),
                "hint": "Based on your latest vital record.",
                "had_vitals": True,
            }
        else:
            hl = life_os_service.get_health_for_day(session, uid, yesterday)
            if hl is not None:
                s = 50
                if hl.sleep_hours is not None:
                    s += min(25, max(0, int((float(hl.sleep_hours) - 5) * 5)))
                if hl.stress_1_10 is not None:
                    s += max(0, 25 - int(hl.stress_1_10) * 2)
                health_score = {
                    "score": max(0, min(100, s)),
                    "hint": "Based on legacy health log (yesterday).",
                    "had_vitals": True,
                }

    snap = {
        "tasks": [{"id": p["id"], "title": p["title"]} for p in priorities],
        "reminders": [],
        "low_stock": {},
        "today_sales": {},
        "authenticated": True,
        "user_id": uid,
        "organization_id": organization_id,
        "daily_score": int(health_score.get("score") or 0),
        "streak_days": 0,
        "habits_completed_today": 0,
        "tasks_completed_today": 0,
    }
    guidance = generate_daily_guidance(snap, memory=None, followups=None)
    ai_insight = (
        str(guidance.get("encouragement") or guidance.get("message") or "")[:800]
        or "Start by setting your top three priorities and logging one health reading."
    )

    return {
        "as_of_utc": now.isoformat(),
        "date": today.isoformat(),
        "weather": weather,
        "priorities": priorities,
        "meetings": [],
        "pending_decisions": [],
        "financial_snapshot": financial,
        "health_score": health_score,
        "ai_insight": ai_insight,
    }


def list_expenses_sync(user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return []
    with factory() as session:
        rows = session.execute(
            select(PersonalExpense)
            .where(PersonalExpense.user_id == uid)
            .order_by(PersonalExpense.spent_at.desc())
            .limit(min(200, max(1, limit)))
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "amount": str(r.amount),
                "currency": r.currency,
                "category": r.category,
                "subcategory": r.subcategory,
                "spent_at": r.spent_at.isoformat(),
                "title": r.title,
                "notes_encrypted": bool(r.notes_encrypted),
            }
            for r in rows
        ]


def create_expense_sync(
    *,
    user_id: int,
    amount: Decimal,
    currency: str,
    category: str,
    subcategory: str,
    spent_at: datetime,
    title: str,
    notes_plain: str | None,
    fernet: Fernet | None,
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return False, "database not configured", None
    nc, ne = _maybe_encrypt(plain=notes_plain, fernet=fernet)
    with factory() as session:
        with session.begin():
            row = PersonalExpense(
                user_id=uid,
                amount=amount,
                currency=(currency or "INR")[:8],
                category=(category or "other")[:64],
                subcategory=(subcategory or "")[:128],
                spent_at=spent_at,
                title=(title or "")[:2000],
                notes_cipher=nc,
                notes_encrypted=ne,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)


def list_loans_sync(user_id: int) -> list[dict[str, Any]]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return []
    with factory() as session:
        rows = session.execute(
            select(PersonalLoan).where(PersonalLoan.user_id == uid).order_by(PersonalLoan.created_at.desc())
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "display_name": r.display_name,
                "loan_kind": r.loan_kind,
                "lender": r.lender,
                "principal_outstanding": str(r.principal_outstanding) if r.principal_outstanding is not None else None,
                "emi_amount": str(r.emi_amount) if r.emi_amount is not None else None,
                "next_due_date": r.next_due_date.isoformat() if r.next_due_date else None,
                "is_closed": r.is_closed,
            }
            for r in rows
        ]


def create_loan_sync(
    *,
    user_id: int,
    display_name: str,
    loan_kind: str,
    lender: str | None,
    principal_outstanding: Decimal | None,
    emi_amount: Decimal | None,
    next_due_date: date | None,
    notes_plain: str | None,
    fernet: Fernet | None,
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return False, "database not configured", None
    nc, ne = _maybe_encrypt(plain=notes_plain, fernet=fernet)
    with factory() as session:
        with session.begin():
            row = PersonalLoan(
                user_id=uid,
                display_name=display_name.strip()[:2000],
                loan_kind=(loan_kind or "other")[:32],
                lender=(lender or None),
                principal_outstanding=principal_outstanding,
                emi_amount=emi_amount,
                next_due_date=next_due_date,
                notes_cipher=nc,
                notes_encrypted=ne,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)


def list_vitals_sync(user_id: int, *, limit: int = 60) -> list[dict[str, Any]]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return []
    with factory() as session:
        rows = session.execute(
            select(VitalRecord)
            .where(VitalRecord.user_id == uid)
            .order_by(VitalRecord.recorded_at.desc())
            .limit(min(200, max(1, limit)))
        ).scalars().all()
        out = []
        for r in rows:
            out.append(
                {
                    "id": int(r.id),
                    "recorded_at": r.recorded_at.isoformat(),
                    "weight_kg": str(r.weight_kg) if r.weight_kg is not None else None,
                    "bp_systolic": r.bp_systolic,
                    "bp_diastolic": r.bp_diastolic,
                    "blood_glucose_mg_dl": str(r.blood_glucose_mg_dl) if r.blood_glucose_mg_dl is not None else None,
                    "sleep_hours": str(r.sleep_hours) if r.sleep_hours is not None else None,
                    "stress_1_10": r.stress_1_10,
                    "water_glasses": r.water_glasses,
                    "notes_encrypted": bool(r.notes_encrypted),
                }
            )
        return out


def create_vital_sync(
    *,
    user_id: int,
    recorded_at: datetime,
    weight_kg: Decimal | None,
    bp_systolic: int | None,
    bp_diastolic: int | None,
    blood_glucose_mg_dl: Decimal | None,
    sleep_hours: Decimal | None,
    stress_1_10: int | None,
    water_glasses: int | None,
    notes_plain: str | None,
    fernet: Fernet | None,
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return False, "database not configured", None
    nc, ne = _maybe_encrypt(plain=notes_plain, fernet=fernet)
    with factory() as session:
        with session.begin():
            row = VitalRecord(
                user_id=uid,
                recorded_at=recorded_at,
                weight_kg=weight_kg,
                bp_systolic=bp_systolic,
                bp_diastolic=bp_diastolic,
                blood_glucose_mg_dl=blood_glucose_mg_dl,
                sleep_hours=sleep_hours,
                stress_1_10=stress_1_10,
                water_glasses=water_glasses,
                notes_cipher=nc,
                notes_encrypted=ne,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)


def list_medicines_sync(user_id: int) -> list[dict[str, Any]]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return []
    with factory() as session:
        rows = session.execute(
            select(MedicineTracker).where(MedicineTracker.user_id == uid).order_by(MedicineTracker.created_at.desc())
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "name": r.name,
                "dosage_text": r.dosage_text,
                "schedule_json": r.schedule_json or {},
                "started_on": r.started_on.isoformat(),
                "ended_on": r.ended_on.isoformat() if r.ended_on else None,
                "is_active": r.is_active,
            }
            for r in rows
        ]


def create_medicine_sync(
    *,
    user_id: int,
    name: str,
    dosage_text: str,
    schedule_json: dict[str, Any],
    started_on: date,
    ended_on: date | None,
    notes_plain: str | None,
    fernet: Fernet | None,
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return False, "database not configured", None
    nc, ne = _maybe_encrypt(plain=notes_plain, fernet=fernet)
    with factory() as session:
        with session.begin():
            row = MedicineTracker(
                user_id=uid,
                name=name.strip()[:500],
                dosage_text=(dosage_text or "")[:2000],
                schedule_json=dict(schedule_json or {}),
                started_on=started_on,
                ended_on=ended_on,
                is_active=True,
                notes_cipher=nc,
                notes_encrypted=ne,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)


def list_doctor_visits_sync(user_id: int) -> list[dict[str, Any]]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return []
    with factory() as session:
        rows = session.execute(
            select(DoctorVisit).where(DoctorVisit.user_id == uid).order_by(DoctorVisit.visited_on.desc())
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "visited_on": r.visited_on.isoformat(),
                "doctor_name": r.doctor_name,
                "specialty": r.specialty,
                "location": r.location,
                "follow_up_date": r.follow_up_date.isoformat() if r.follow_up_date else None,
                "diagnosis_encrypted": bool(r.diagnosis_encrypted),
            }
            for r in rows
        ]


def create_doctor_visit_sync(
    *,
    user_id: int,
    visited_on: date,
    doctor_name: str,
    specialty: str | None,
    location: str | None,
    diagnosis_plain: str | None,
    prescription_plain: str | None,
    follow_up_date: date | None,
    fernet: Fernet | None,
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return False, "database not configured", None
    dc, de = _maybe_encrypt(plain=diagnosis_plain, fernet=fernet)
    pc, pe = _maybe_encrypt(plain=prescription_plain, fernet=fernet)
    with factory() as session:
        with session.begin():
            row = DoctorVisit(
                user_id=uid,
                visited_on=visited_on,
                doctor_name=doctor_name.strip()[:500],
                specialty=(specialty or None),
                location=(location or None),
                diagnosis_cipher=dc,
                prescription_cipher=pc,
                diagnosis_encrypted=de or pe,
                follow_up_date=follow_up_date,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)


def list_budgets_sync(user_id: int) -> list[dict[str, Any]]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return []
    with factory() as session:
        rows = session.execute(
            select(PersonalBudget).where(PersonalBudget.user_id == uid).order_by(PersonalBudget.period_start.desc())
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "category": r.category,
                "subcategory": r.subcategory,
                "budget_amount": str(r.budget_amount),
                "currency": r.currency,
                "overspend_alert_pct": int(r.overspend_alert_pct),
            }
            for r in rows
        ]


def create_budget_sync(
    *,
    user_id: int,
    period_start: date,
    period_end: date,
    category: str,
    subcategory: str,
    budget_amount: Decimal,
    currency: str,
    overspend_alert_pct: int,
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return False, "database not configured", None
    if period_end < period_start:
        return False, "period_end before period_start", None
    with factory() as session:
        with session.begin():
            row = PersonalBudget(
                user_id=uid,
                period_start=period_start,
                period_end=period_end,
                category=category[:64],
                subcategory=(subcategory or "")[:128],
                budget_amount=budget_amount,
                currency=(currency or "INR")[:8],
                overspend_alert_pct=max(0, min(100, int(overspend_alert_pct))),
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)


def list_research_projects_sync(user_id: int) -> list[dict[str, Any]]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return []
    with factory() as session:
        rows = session.execute(
            select(ResearchProject).where(ResearchProject.user_id == uid).order_by(ResearchProject.updated_at.desc())
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "title": r.title,
                "description": (r.description or "")[:500],
                "status": r.status,
                "links_json": r.links_json or {},
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]


def create_research_project_sync(
    *,
    user_id: int,
    title: str,
    description: str | None,
    links_json: dict[str, Any],
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    factory = _factory()
    if factory is None or uid <= 0:
        return False, "database not configured", None
    with factory() as session:
        with session.begin():
            row = ResearchProject(
                user_id=uid,
                title=title.strip()[:2000],
                description=(description or None),
                status="active",
                links_json=dict(links_json or {}),
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)
