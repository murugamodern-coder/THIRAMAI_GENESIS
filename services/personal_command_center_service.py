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
from sqlalchemy.orm import Session
from core.database import get_session_factory
from core.db.models import (
    DoctorVisit,
    Habit,
    HealthLog,
    Invoice,
    MedicineTracker,
    PersonalBudget,
    PersonalExpense,
    PersonalLoan,
    PersonalMeeting,
    PersonalMission,
    ResearchProject,
    User,
    VitalRecord,
)
from core.personal_ai_engine import generate_daily_guidance
from services import life_os_service
from services import personal_meetings_service
from services.personal_crypto import encrypt_utf8
from services.personal_os_aggregate import MISSION_OPEN_STATUSES, build_personal_today_sync

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
    meetings_today_payload: list[dict[str, Any]] = []
    meetings_upcoming_7d_count = 0
    meeting_soon_alert: dict[str, Any] | None = None

    if factory is None:
        return {
            "as_of_utc": now.isoformat(),
            "date": today.isoformat(),
            "weather": weather,
            "priorities": [],
            "meetings": [],
            "meetings_upcoming_7d_count": 0,
            "meeting_soon_alert": None,
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

        try:
            meetings_today_payload, meetings_upcoming_7d_count, meeting_soon_alert = (
                personal_meetings_service.meetings_morning_brief_payload(
                    session,
                    user_id=uid,
                    organization_id=int(organization_id),
                    now=now,
                )
            )
        except Exception:
            meetings_today_payload, meetings_upcoming_7d_count, meeting_soon_alert = [], 0, None

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
        "meetings": meetings_today_payload,
        "meetings_upcoming_7d_count": meetings_upcoming_7d_count,
        "meeting_soon_alert": meeting_soon_alert,
        "pending_decisions": [],
        "financial_snapshot": financial,
        "health_score": health_score,
        "ai_insight": ai_insight,
    }


def _user_display_name(session: Session, uid: int) -> str:
    u = session.get(User, int(uid))
    if u is None:
        return "there"
    un = (getattr(u, "username", None) or "").strip()
    if un:
        return un
    local = (u.email or "").split("@", 1)[0].strip()
    return local or "there"


def _days_since_last_health_activity(session: Session, uid: int) -> int | None:
    """Days since last vital record or legacy health log day; None if never logged."""
    uid = int(uid)
    last_v = session.execute(
        select(VitalRecord.recorded_at)
        .where(VitalRecord.user_id == uid)
        .order_by(VitalRecord.recorded_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    last_h = session.execute(
        select(HealthLog.logged_on)
        .where(HealthLog.user_id == uid)
        .order_by(HealthLog.logged_on.desc())
        .limit(1)
    ).scalar_one_or_none()
    today = datetime.now(timezone.utc).date()
    candidates: list[date] = []
    if last_v is not None:
        dt = last_v if isinstance(last_v, datetime) else datetime.fromisoformat(str(last_v))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        candidates.append(dt.date())
    if last_h is not None:
        if isinstance(last_h, date):
            candidates.append(last_h)
        else:
            try:
                candidates.append(date.fromisoformat(str(last_h)[:10]))
            except Exception:
                pass
    if not candidates:
        return None
    most_recent = max(candidates)
    return (today - most_recent).days


def build_today_brief_sync(
    *,
    user_id: int,
    organization_id: int,
    fernet: Fernet | None = None,
) -> dict[str, Any]:
    """
    Unified hero \"Today\" payload: morning brief + business snapshot + capped proactive alerts.
    """
    uid = int(user_id)
    oid = int(organization_id)
    brief = build_morning_brief_sync(user_id=uid, organization_id=oid, fernet=fernet)
    agg = build_personal_today_sync(user_id=uid, organization_id=oid, low_stock_threshold=5)

    lat = float(os.getenv("PERSONAL_OS_WEATHER_LAT") or "0")
    lon = float(os.getenv("PERSONAL_OS_WEATHER_LON") or "0")
    weather_configured = bool(lat and lon and abs(lat) <= 90 and abs(lon) <= 180)

    display_name = "there"
    factory = _factory()
    if factory is not None and uid > 0:
        with factory() as session:
            display_name = _user_display_name(session, uid)

    # Format first name for greeting (avoid shouting full email)
    greet = display_name.strip() or "there"
    if greet != "there":
        greet = greet.replace("_", " ").split()[0]
        greet = greet[:1].upper() + greet[1:] if greet else "there"

    focus_task: dict[str, Any] | None = None
    for p in brief.get("priorities") or []:
        if str(p.get("priority") or "").upper() == "P1":
            focus_task = p
            break
    if focus_task is None and brief.get("priorities"):
        focus_task = brief["priorities"][0]

    now = datetime.now(timezone.utc)
    meetings_raw = list(brief.get("meetings") or [])
    next_id: int | None = None
    future: list[tuple[datetime, int]] = []
    for m in meetings_raw:
        mid = int(m.get("id") or 0)
        sa = m.get("scheduled_at")
        if not sa or not mid:
            continue
        try:
            raw = str(sa).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= now:
                future.append((dt, mid))
        except Exception:
            continue
    if future:
        future.sort(key=lambda x: x[0])
        next_id = future[0][1]
    elif meetings_raw:
        try:
            scored: list[tuple[datetime, int]] = []
            for m in meetings_raw:
                mid = int(m.get("id") or 0)
                sa = m.get("scheduled_at")
                if not sa or not mid:
                    continue
                raw = str(sa).replace("Z", "+00:00")
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                scored.append((dt, mid))
            if scored:
                scored.sort(key=lambda x: x[0])
                next_id = scored[0][1]
        except Exception:
            next_id = int(meetings_raw[0].get("id") or 0) or None

    meetings_today: list[dict[str, Any]] = []
    for m in meetings_raw:
        mid = int(m.get("id") or 0)
        meetings_today.append({**m, "is_next": bool(next_id and mid == next_id)})

    business_snapshot: dict[str, Any] = {"ok": False}
    sales = agg.get("today_sales") if isinstance(agg.get("today_sales"), dict) else {}
    pending_invoices_count = 0
    pending_invoices_total_inr: str | None = None
    if oid > 0 and factory is not None:
        with factory() as session:
            pending_invoices_count = int(
                session.execute(
                    select(func.count())
                    .select_from(Invoice)
                    .where(
                        Invoice.organization_id == oid,
                        Invoice.payment_status == "unpaid",
                    )
                ).scalar()
                or 0
            )
            total_unpaid = session.execute(
                select(func.coalesce(func.sum(Invoice.grand_total_inr), 0)).where(
                    Invoice.organization_id == oid,
                    Invoice.payment_status == "unpaid",
                )
            ).scalar()
            if total_unpaid is not None:
                pending_invoices_total_inr = str(Decimal(str(total_unpaid)).quantize(Decimal("0.01")))
    if oid > 0 and sales.get("ok"):
        rev = sales.get("revenue_inr") if isinstance(sales.get("revenue_inr"), dict) else {}
        business_snapshot = {
            "ok": True,
            "revenue_today_inr": rev.get("today"),
            "revenue_week_inr": rev.get("this_week"),
            "revenue_month_inr": rev.get("this_month"),
            "top_selling_products": sales.get("top_selling_products") or [],
            "pending_invoices_count": pending_invoices_count,
            "pending_invoices_total_inr": pending_invoices_total_inr,
        }
    elif oid > 0:
        business_snapshot = {
            "ok": True,
            "note": "revenue_summary_unavailable",
            "revenue_today_inr": None,
            "revenue_week_inr": None,
            "revenue_month_inr": None,
            "top_selling_products": [],
            "pending_invoices_count": pending_invoices_count,
            "pending_invoices_total_inr": pending_invoices_total_inr,
        }

    alerts: list[dict[str, Any]] = []
    soon = brief.get("meeting_soon_alert")
    if isinstance(soon, dict) and soon.get("message"):
        alerts.append(
            {
                "code": "meeting_soon",
                "severity": "high",
                "message": str(soon["message"]),
            }
        )

    fin = brief.get("financial_snapshot") if isinstance(brief.get("financial_snapshot"), dict) else {}
    today_d = datetime.now(timezone.utc).date()
    for emi in fin.get("upcoming_emis") or []:
        if not isinstance(emi, dict):
            continue
        due_s = emi.get("due")
        if not due_s:
            continue
        try:
            d_str = str(due_s)[:10]
            due_d = date.fromisoformat(d_str)
            days_until = (due_d - today_d).days
            if 0 <= days_until <= 7:
                name = str(emi.get("name") or "Loan").strip() or "Loan"
                if days_until == 0:
                    msg = f"EMI due today: {name}"
                elif days_until == 1:
                    msg = f"EMI due tomorrow: {name}"
                else:
                    msg = f"EMI due in {days_until} days: {name}"
                alerts.append({"code": "emi_due", "severity": "medium", "message": msg})
                break
        except Exception:
            continue

    low = agg.get("low_stock") if isinstance(agg.get("low_stock"), dict) else {}
    items = low.get("items") if isinstance(low.get("items"), list) else []
    low_stock_count = int(low.get("count") or 0) if isinstance(low.get("count"), int) else len(items)
    if oid > 0 and items:
        first = items[0] if isinstance(items[0], dict) else {}
        sku = str(first.get("sku_name") or first.get("name") or "Item").strip() or "Item"
        qty = first.get("quantity")
        qbit = f" (qty {qty})" if qty is not None else ""
        alerts.append(
            {
                "code": "low_stock",
                "severity": "high",
                "message": f"Low stock alert: {sku}{qbit}",
            }
        )

    days_stale: int | None = None
    if factory is not None and uid > 0:
        with factory() as session:
            days_stale = _days_since_last_health_activity(session, uid)
    if days_stale is not None and days_stale >= 2:
        alerts.append(
            {
                "code": "health_stale",
                "severity": "medium",
                "message": (
                    f"You haven't logged health in {days_stale} days."
                    if days_stale > 2
                    else "You haven't logged health in 2 days."
                ),
            }
        )

    sev_rank = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: sev_rank.get(str(a.get("severity")), 9))
    _alert_urls = {
        "meeting_soon": "#/today",
        "emi_due": "#/personal/finance",
        "low_stock": "#/dashboard/inventory",
        "health_stale": "#/personal/health",
    }
    proactive_alerts: list[dict[str, Any]] = []
    for a in alerts[:3]:
        code = str(a.get("code") or "notice")
        proactive_alerts.append(
            {
                **a,
                "type": code,
                "action_url": _alert_urls.get(code, "#/today"),
            }
        )

    nudges = agg.get("meeting_nudges") if isinstance(agg.get("meeting_nudges"), list) else []

    day_key = str(brief.get("date") or "")[:10]
    try:
        day_of_week = date.fromisoformat(day_key).strftime("%A") if day_key else ""
    except Exception:
        day_of_week = ""

    focus_out = dict(focus_task) if focus_task else None
    if focus_out:
        focus_out["due_date"] = focus_out.get("deadline")

    def _meeting_location_display(m: dict[str, Any]) -> str:
        lt = str(m.get("location_type") or "")
        name = (m.get("location_name") or "").strip()
        addr = (m.get("location_address") or "").strip()
        if lt == "online":
            return "Online"
        if name and addr:
            return f"{name} · {addr[:120]}"
        return name or addr or (lt.replace("_", " ").title() if lt else "—")

    meetings_enriched: list[dict[str, Any]] = []
    for m in meetings_today:
        mt = str(m.get("meeting_type") or "other")
        meetings_enriched.append({**m, "location": _meeting_location_display(m), "type": mt})
    meetings_today = meetings_enriched

    next_meeting: dict[str, Any] | None = None
    nx = next((x for x in meetings_today if x.get("is_next")), None)
    if nx and nx.get("scheduled_at"):
        try:
            raw_dt = str(nx["scheduled_at"]).replace("Z", "+00:00")
            dt_nx = datetime.fromisoformat(raw_dt)
            if dt_nx.tzinfo is None:
                dt_nx = dt_nx.replace(tzinfo=timezone.utc)
            delta_min = int((dt_nx - now).total_seconds() // 60)
            if delta_min < 0:
                countdown = "Started"
            elif delta_min == 0:
                countdown = "Starting now"
            else:
                countdown = f"in {delta_min} minutes"
            next_meeting = {**nx, "countdown_text": countdown, "minutes_until": delta_min}
        except Exception:
            next_meeting = {**nx, "countdown_text": None, "minutes_until": None}

    upcoming_emis_next: dict[str, Any] | None = None
    horizon_end = today_d + timedelta(days=30)
    for emi in fin.get("upcoming_emis") or []:
        if not isinstance(emi, dict):
            continue
        due_s = emi.get("due")
        if not due_s:
            continue
        try:
            due_d = date.fromisoformat(str(due_s)[:10])
            if today_d <= due_d <= horizon_end:
                upcoming_emis_next = emi
                break
        except Exception:
            continue

    habit_streak_best = 0
    tasks_completed_today = int(agg.get("tasks_completed_today") or 0)
    open_missions_total = len(agg.get("tasks") or [])
    if factory is not None and uid > 0:
        with factory() as session:
            habits = list(
                session.execute(select(Habit).where(Habit.user_id == uid, Habit.is_active.is_(True))).scalars().all()
            )
            if habits:
                habit_streak_best = max(int(h.streak_count or 0) for h in habits)

    insight_line = str(brief.get("ai_insight") or "").strip()

    return {
        "ok": True,
        "as_of_utc": brief.get("as_of_utc"),
        "date": brief.get("date"),
        "day_of_week": day_of_week,
        "greeting": {
            "display_name": greet,
            "server_time_utc": datetime.now(timezone.utc).isoformat(),
        },
        "weather": brief.get("weather"),
        "weather_configured": weather_configured,
        "focus_task": focus_out,
        "meetings_today": meetings_today,
        "next_meeting": next_meeting,
        "health_score": brief.get("health_score"),
        "health_score_yesterday": brief.get("health_score"),
        "business_snapshot": business_snapshot,
        "proactive_alerts": proactive_alerts,
        "ai_insight": insight_line,
        "motivational_insight": insight_line,
        "upcoming_emis": upcoming_emis_next,
        "low_stock_count": low_stock_count,
        "habit_streak_days": habit_streak_best,
        "tasks_progress": {
            "completed_today": tasks_completed_today,
            "open_total": open_missions_total,
        },
        "meeting_nudges": nudges[:5],
        "meetings_upcoming_7d_count": brief.get("meetings_upcoming_7d_count", 0),
        "financial_snapshot": fin,
    }


def build_weekly_review_sync(*, user_id: int, organization_id: int) -> dict[str, Any]:
    """Last 7 days snapshot for weekly review UI (tasks, health, spend, meetings)."""
    uid = int(user_id)
    oid = int(organization_id)
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    out: dict[str, Any] = {
        "ok": True,
        "period_start_utc": start.isoformat(),
        "period_end_utc": now.isoformat(),
    }
    factory = _factory()
    if factory is None or uid <= 0:
        return {**out, "note": "database_or_user_unavailable"}

    with factory() as session:
        missions_done = int(
            session.execute(
                select(func.count())
                .select_from(PersonalMission)
                .where(
                    PersonalMission.user_id == uid,
                    ~PersonalMission.status.in_(tuple(MISSION_OPEN_STATUSES)),
                    PersonalMission.updated_at >= start,
                )
            ).scalar()
            or 0
        )
        missions_open = int(
            session.execute(
                select(func.count())
                .select_from(PersonalMission)
                .where(
                    PersonalMission.user_id == uid,
                    PersonalMission.status.in_(tuple(MISSION_OPEN_STATUSES)),
                )
            ).scalar()
            or 0
        )
        spent_week = session.execute(
            select(func.coalesce(func.sum(PersonalExpense.amount), 0)).where(
                PersonalExpense.user_id == uid,
                PersonalExpense.spent_at >= start,
            )
        ).scalar()
        health_logs = int(
            session.execute(
                select(func.count(func.distinct(HealthLog.logged_on)))
                .where(HealthLog.user_id == uid, HealthLog.logged_on >= start.date())
            ).scalar()
            or 0
        )
        meetings_week = 0
        if oid > 0:
            meetings_week = int(
                session.execute(
                    select(func.count())
                    .select_from(PersonalMeeting)
                    .where(
                        PersonalMeeting.user_id == uid,
                        PersonalMeeting.organization_id == oid,
                        PersonalMeeting.scheduled_at >= start,
                    )
                ).scalar()
                or 0
            )

    priorities = []
    if factory is not None:
        brief = build_morning_brief_sync(user_id=uid, organization_id=oid, fernet=None)
        for p in (brief.get("priorities") or [])[:5]:
            if isinstance(p, dict) and p.get("title"):
                priorities.append(
                    {"title": p.get("title"), "priority": p.get("priority"), "deadline": p.get("deadline")}
                )

    return {
        **out,
        "tasks_completed_week": missions_done,
        "tasks_open_now": missions_open,
        "personal_spend_week_inr": str(Decimal(str(spent_week or 0)).quantize(Decimal("0.01"))),
        "health_logs_logged_days_approx": health_logs,
        "meetings_scheduled_week": meetings_week,
        "next_week_priorities_suggested": priorities,
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
