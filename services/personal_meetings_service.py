"""Personal meetings / appointments — CRUD and morning-brief slices."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import PersonalMeeting

MEETING_TYPES = frozenset(
    {
        "personal",
        "business",
        "family",
        "friends",
        "medical",
        "legal",
        "government",
        "vendor",
        "client",
        "team",
        "interview",
        "site_visit",
        "other",
    }
)
LOCATION_TYPES = frozenset(
    {
        "in_person",
        "online",
        "phone_call",
        "home",
        "office",
        "client_office",
        "restaurant",
        "hospital",
        "court",
        "site",
        "other",
    }
)
MEETING_STATUSES = frozenset({"scheduled", "completed", "cancelled", "rescheduled"})
ACTIVE_STATUSES = frozenset({"scheduled", "rescheduled"})
PRIORITIES = frozenset({"low", "normal", "high", "urgent"})
ARRANGED_BY = frozenset({"self", "other"})


def normalize_attendees(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for row in raw[:50]:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "name": str(row.get("name") or "")[:200],
                "phone": str(row.get("phone") or "")[:64],
                "email": str(row.get("email") or "")[:320],
                "role": str(row.get("role") or "")[:120],
            }
        )
    return out


def serialize_meeting(m: PersonalMeeting) -> dict[str, Any]:
    att = m.attendees_json
    if not isinstance(att, list):
        att = []
    return {
        "id": int(m.id),
        "user_id": int(m.user_id),
        "organization_id": int(m.organization_id),
        "title": m.title,
        "meeting_type": m.meeting_type,
        "location_type": m.location_type,
        "location_name": m.location_name or "",
        "location_address": m.location_address,
        "location_maps_url": m.location_maps_url,
        "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
        "duration_minutes": int(m.duration_minutes or 60),
        "status": m.status,
        "priority": m.priority,
        "agenda": m.agenda,
        "notes": m.notes,
        "outcome": m.outcome,
        "arranged_by": m.arranged_by,
        "organizer_name": m.organizer_name,
        "organizer_phone": m.organizer_phone,
        "organizer_email": m.organizer_email,
        "attendees_json": att,
        "reminder_minutes": int(m.reminder_minutes or 30),
        "is_recurring": bool(m.is_recurring),
        "recurrence_rule": m.recurrence_rule,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def meetings_morning_brief_payload(
    session: Session,
    *,
    user_id: int,
    organization_id: int,
    now: datetime,
) -> tuple[list[dict[str, Any]], int, dict[str, Any] | None]:
    """Today's meetings (serialized), count in next 7 days (incl. today), optional soon alert."""
    uid = int(user_id)
    oid = int(organization_id)
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    week_end = day_start + timedelta(days=7)

    today_rows = session.execute(
        select(PersonalMeeting)
        .where(
            PersonalMeeting.user_id == uid,
            PersonalMeeting.organization_id == oid,
            PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
            PersonalMeeting.scheduled_at >= day_start,
            PersonalMeeting.scheduled_at < day_end,
        )
        .order_by(PersonalMeeting.scheduled_at.asc())
    ).scalars().all()
    meetings_today = [serialize_meeting(m) for m in today_rows]

    upcoming_n = session.execute(
        select(PersonalMeeting.id).where(
            PersonalMeeting.user_id == uid,
            PersonalMeeting.organization_id == oid,
            PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
            PersonalMeeting.scheduled_at >= day_start,
            PersonalMeeting.scheduled_at < week_end,
        )
    ).all()
    count_7d = len(upcoming_n)

    soon_end = now + timedelta(minutes=30)
    soon_row = session.execute(
        select(PersonalMeeting)
        .where(
            PersonalMeeting.user_id == uid,
            PersonalMeeting.organization_id == oid,
            PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
            PersonalMeeting.scheduled_at >= now,
            PersonalMeeting.scheduled_at <= soon_end,
        )
        .order_by(PersonalMeeting.scheduled_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    soon_alert: dict[str, Any] | None = None
    if soon_row is not None and soon_row.scheduled_at:
        delta_min = max(0, int((soon_row.scheduled_at - now).total_seconds() // 60))
        soon_alert = {
            "meeting_id": int(soon_row.id),
            "title": soon_row.title,
            "scheduled_at": soon_row.scheduled_at.isoformat(),
            "minutes_until": delta_min,
            "message": f"Starts in {delta_min} min — {soon_row.title}",
        }

    return meetings_today, count_7d, soon_alert


def list_meetings(
    session: Session,
    *,
    user_id: int,
    organization_id: int,
    date_from: date | None,
    date_to: date | None,
    meeting_type: str | None,
    status: str | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    uid = int(user_id)
    oid = int(organization_id)
    q = select(PersonalMeeting).where(
        PersonalMeeting.user_id == uid,
        PersonalMeeting.organization_id == oid,
    )
    if date_from is not None:
        start = datetime.combine(date_from, datetime.min.time()).replace(tzinfo=timezone.utc)
        q = q.where(PersonalMeeting.scheduled_at >= start)
    if date_to is not None:
        end = datetime.combine(date_to, datetime.max.time()).replace(tzinfo=timezone.utc)
        q = q.where(PersonalMeeting.scheduled_at <= end)
    if meeting_type and meeting_type.strip():
        q = q.where(PersonalMeeting.meeting_type == meeting_type.strip())
    if status and status.strip():
        q = q.where(PersonalMeeting.status == status.strip())
    q = q.order_by(PersonalMeeting.scheduled_at.asc()).limit(min(200, max(1, limit)))
    rows = session.execute(q).scalars().all()
    return [serialize_meeting(m) for m in rows]


def list_today(session: Session, *, user_id: int, organization_id: int, now: datetime) -> list[dict[str, Any]]:
    uid = int(user_id)
    oid = int(organization_id)
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    rows = session.execute(
        select(PersonalMeeting)
        .where(
            PersonalMeeting.user_id == uid,
            PersonalMeeting.organization_id == oid,
            PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
            PersonalMeeting.scheduled_at >= day_start,
            PersonalMeeting.scheduled_at < day_end,
        )
        .order_by(PersonalMeeting.scheduled_at.asc())
        .limit(50)
    ).scalars().all()
    return [serialize_meeting(m) for m in rows]


def list_upcoming(session: Session, *, user_id: int, organization_id: int, now: datetime) -> list[dict[str, Any]]:
    uid = int(user_id)
    oid = int(organization_id)
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    week_end = day_start + timedelta(days=7)
    rows = session.execute(
        select(PersonalMeeting)
        .where(
            PersonalMeeting.user_id == uid,
            PersonalMeeting.organization_id == oid,
            PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
            PersonalMeeting.scheduled_at >= day_start,
            PersonalMeeting.scheduled_at < week_end,
        )
        .order_by(PersonalMeeting.scheduled_at.asc())
        .limit(100)
    ).scalars().all()
    return [serialize_meeting(m) for m in rows]


def get_meeting_or_none(
    session: Session, *, user_id: int, organization_id: int, meeting_id: int
) -> PersonalMeeting | None:
    return session.execute(
        select(PersonalMeeting).where(
            PersonalMeeting.id == int(meeting_id),
            PersonalMeeting.user_id == int(user_id),
            PersonalMeeting.organization_id == int(organization_id),
        )
    ).scalar_one_or_none()


def create_meeting(
    session: Session,
    *,
    user_id: int,
    organization_id: int,
    title: str,
    meeting_type: str,
    location_type: str,
    location_name: str,
    location_address: str | None,
    location_maps_url: str | None,
    scheduled_at: datetime,
    duration_minutes: int,
    priority: str,
    agenda: str | None,
    arranged_by: str,
    organizer_name: str | None,
    organizer_phone: str | None,
    organizer_email: str | None,
    attendees_json: list[dict[str, Any]],
    reminder_minutes: int,
    is_recurring: bool,
    recurrence_rule: str | None,
) -> PersonalMeeting:
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    row = PersonalMeeting(
        user_id=int(user_id),
        organization_id=int(organization_id),
        title=title.strip()[:4000],
        meeting_type=meeting_type,
        location_type=location_type,
        location_name=(location_name or "")[:2000],
        location_address=(location_address or None),
        location_maps_url=(location_maps_url or None),
        scheduled_at=scheduled_at,
        duration_minutes=max(5, min(24 * 60, int(duration_minutes))),
        status="scheduled",
        priority=priority,
        agenda=agenda,
        arranged_by=arranged_by,
        organizer_name=organizer_name,
        organizer_phone=(organizer_phone or None),
        organizer_email=(organizer_email or None),
        attendees_json=normalize_attendees(attendees_json),
        reminder_minutes=max(0, min(24 * 60, int(reminder_minutes))),
        is_recurring=bool(is_recurring),
        recurrence_rule=(recurrence_rule or None),
    )
    session.add(row)
    session.flush()
    return row


def update_meeting_fields(
    m: PersonalMeeting,
    *,
    title: str | None = None,
    meeting_type: str | None = None,
    location_type: str | None = None,
    location_name: str | None = None,
    location_address: str | None = None,
    location_maps_url: str | None = None,
    scheduled_at: datetime | None = None,
    duration_minutes: int | None = None,
    status: str | None = None,
    priority: str | None = None,
    agenda: str | None = None,
    notes: str | None = None,
    outcome: str | None = None,
    arranged_by: str | None = None,
    organizer_name: str | None = None,
    organizer_phone: str | None = None,
    organizer_email: str | None = None,
    attendees_json: list[dict[str, Any]] | None = None,
    reminder_minutes: int | None = None,
    is_recurring: bool | None = None,
    recurrence_rule: str | None = None,
) -> None:
    if title is not None:
        m.title = title.strip()[:4000]
    if meeting_type is not None:
        m.meeting_type = meeting_type
    if location_type is not None:
        m.location_type = location_type
    if location_name is not None:
        m.location_name = location_name[:2000]
    if location_address is not None:
        m.location_address = location_address
    if location_maps_url is not None:
        m.location_maps_url = location_maps_url
    if scheduled_at is not None:
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        m.scheduled_at = scheduled_at
    if duration_minutes is not None:
        m.duration_minutes = max(5, min(24 * 60, int(duration_minutes)))
    if status is not None:
        m.status = status
    if priority is not None:
        m.priority = priority
    if agenda is not None:
        m.agenda = agenda
    if notes is not None:
        m.notes = notes
    if outcome is not None:
        m.outcome = outcome
    if arranged_by is not None:
        m.arranged_by = arranged_by
    if organizer_name is not None:
        m.organizer_name = organizer_name
    if organizer_phone is not None:
        m.organizer_phone = organizer_phone
    if organizer_email is not None:
        m.organizer_email = organizer_email
    if attendees_json is not None:
        m.attendees_json = normalize_attendees(attendees_json)
    if reminder_minutes is not None:
        m.reminder_minutes = max(0, min(24 * 60, int(reminder_minutes)))
    if is_recurring is not None:
        m.is_recurring = bool(is_recurring)
    if recurrence_rule is not None:
        m.recurrence_rule = recurrence_rule
