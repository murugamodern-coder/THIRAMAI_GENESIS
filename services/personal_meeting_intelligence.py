"""
Smart meeting engine — reminders (deduped notifications), conflict checks, heuristics, ICS, follow-up missions.

Non-LLM heuristics only; keeps ``personal_meetings_service`` CRUD-focused.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core.database import get_session_factory, session_scope
from core.db.models import PersonalMeeting
from core.observability import log_event, new_request_id
from services.personal_meetings_service import ACTIVE_STATUSES, serialize_meeting

_log = logging.getLogger("thiramai.personal_meeting_intelligence")

NOTIFICATION_DEDUPE_CONSTRAINT = "uq_notifications_org_dedupe"

# meeting_type -> (suggested_duration_minutes, agenda_template)
_MEETING_HEURISTICS: dict[str, tuple[int, str]] = {
    "client": (30, "Intro, needs discovery, proposal / next steps"),
    "vendor": (45, "Scope, pricing, SLA, follow-up owner"),
    "team": (60, "Goals, blockers, decisions, action owners"),
    "interview": (45, "Role fit, compensation band, timeline, questions"),
    "medical": (20, "Symptoms, history, questions for clinician"),
    "legal": (60, "Matter summary, documents, desired outcome"),
    "government": (45, "Forms, IDs, reference numbers, documents checklist"),
    "site_visit": (90, "Arrival, site checklist, safety, photos, punch list"),
    "business": (45, "Objective, decisions, owners, timeline"),
    "family": (30, "Logistics, decisions, calendar sync"),
    "friends": (30, "Plan, location, who brings what"),
    "personal": (30, "Intent, outcomes, self-care check-in"),
}


def suggest_duration_and_agenda(meeting_type: str) -> dict[str, Any]:
    """Rule-based suggestions (no LLM)."""
    key = (meeting_type or "other").strip().lower()
    dur, agenda = _MEETING_HEURISTICS.get(key, (45, "Objective, agenda items, decisions, next actions"))
    return {
        "meeting_type": key,
        "suggested_duration_minutes": dur,
        "agenda_template": agenda,
    }


def find_overlapping_meeting_ids(
    session: Session,
    *,
    user_id: int,
    organization_id: int,
    scheduled_at: datetime,
    duration_minutes: int,
    exclude_meeting_id: int | None = None,
) -> list[int]:
    """Return IDs of **active** meetings whose time ranges overlap [start, end)."""
    uid = int(user_id)
    oid = int(organization_id)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    start = scheduled_at
    end = start + timedelta(minutes=max(1, int(duration_minutes or 60)))

    stmt = select(PersonalMeeting).where(
        PersonalMeeting.user_id == uid,
        PersonalMeeting.organization_id == oid,
        PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
    )
    if exclude_meeting_id is not None and int(exclude_meeting_id) > 0:
        stmt = stmt.where(PersonalMeeting.id != int(exclude_meeting_id))

    conflicts: list[int] = []
    for m in session.execute(stmt).scalars().all():
        if m.scheduled_at is None:
            continue
        ms = m.scheduled_at
        if ms.tzinfo is None:
            ms = ms.replace(tzinfo=timezone.utc)
        dur = max(1, int(m.duration_minutes or 60))
        mend = ms + timedelta(minutes=dur)
        if start < mend and ms < end:
            conflicts.append(int(m.id))
    return sorted(set(conflicts))


def ics_escape(text: str | None) -> str:
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return (
        s.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_meeting_ics(m: PersonalMeeting) -> str:
    """RFC 5545-style single VEVENT (UTC)."""
    if m.scheduled_at is None:
        raise ValueError("scheduled_at required")
    start = m.scheduled_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    start = start.astimezone(timezone.utc)
    end = start + timedelta(minutes=max(1, int(m.duration_minutes or 60)))
    fmt = "%Y%m%dT%H%M%SZ"
    uid = f"thiramai-meeting-{m.id}@thiramai.genesis"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//THIRAMAI//Personal Meeting//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}",
        f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{ics_escape(m.title)}",
        f"DESCRIPTION:{ics_escape(m.agenda or m.notes or '')}",
        f"LOCATION:{ics_escape(m.location_name or '')}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def follow_up_mission_title(m: PersonalMeeting) -> str:
    """Title for auto-created follow-up mission."""
    title = (m.title or "Meeting").strip()[:120]
    if m.meeting_type == "client":
        who = (m.organizer_name or "").strip() if (m.arranged_by or "") == "other" else ""
        if who:
            return f"Follow up with {who} — {title}"
        for row in m.attendees_json or []:
            if isinstance(row, dict) and (row.get("name") or "").strip():
                return f"Follow up with {(row.get('name') or '').strip()} — {title}"
        return f"Follow up: {title}"
    return f"Follow up: {title}"


def list_meeting_nudges_sync(
    session: Session,
    *,
    user_id: int,
    organization_id: int,
    now: datetime | None = None,
    horizon_minutes: int = 120,
) -> list[dict[str, Any]]:
    """
    Read-only: meetings starting within ``horizon_minutes`` (for /personal/today + proactive).
    """
    uid = int(user_id)
    oid = int(organization_id)
    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    end = n + timedelta(minutes=max(5, min(24 * 60, horizon_minutes)))
    rows = session.execute(
        select(PersonalMeeting)
        .where(
            PersonalMeeting.user_id == uid,
            PersonalMeeting.organization_id == oid,
            PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
            PersonalMeeting.scheduled_at > n,
            PersonalMeeting.scheduled_at <= end,
        )
        .order_by(PersonalMeeting.scheduled_at.asc())
        .limit(12)
    ).scalars().all()
    out: list[dict[str, Any]] = []
    for m in rows:
        if m.scheduled_at is None:
            continue
        st = m.scheduled_at if m.scheduled_at.tzinfo else m.scheduled_at.replace(tzinfo=timezone.utc)
        mins = max(0, int((st - n).total_seconds() // 60))
        d = serialize_meeting(m)
        d["minutes_until"] = mins
        out.append(d)
    return out


def notify_meeting_reminders_for_session(session: Session, *, now: datetime | None = None) -> int:
    """
    Insert org notifications for meetings entering the per-meeting reminder window.
    Dedupe: ``meeting_reminder:{meeting_id}:{scheduled_at_epoch}`` per org.
    """
    from core.db.models import Notification

    n = now or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)

    rows = session.execute(
        select(PersonalMeeting).where(
            PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
        )
    ).scalars().all()

    created = 0
    for m in rows:
        if m.scheduled_at is None:
            continue
        st = m.scheduled_at
        if st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        if st <= n:
            continue
        rem = max(0, int(m.reminder_minutes or 30))
        window_start = st - timedelta(minutes=rem)
        if not (window_start <= n < st):
            continue
        oid = int(m.organization_id)
        mid = int(m.id)
        dedupe = f"meeting_reminder:{mid}:{int(st.timestamp())}"
        mins_left = max(0, int((st - n).total_seconds() // 60))
        title = (m.title or "Meeting").strip()[:200]
        body = f"**Meeting in ~{mins_left} min:** {title}\n\nStarts at **{st.strftime('%Y-%m-%d %H:%M UTC')}** ({m.meeting_type})."
        payload: dict[str, Any] = {
            "user_id": int(m.user_id),
            "meeting_id": mid,
            "scheduled_at": st.isoformat(),
            "minutes_until": mins_left,
            "meeting_type": m.meeting_type,
        }
        stmt = insert(Notification).values(
            organization_id=oid,
            kind="meeting_reminder",
            severity="info",
            title=f"Meeting soon: {title[:120]}",
            body=body,
            reference_type="personal_meeting",
            reference_id=mid,
            payload=payload,
            dedupe_key=dedupe,
        )
        stmt = stmt.on_conflict_do_nothing(constraint=NOTIFICATION_DEDUPE_CONSTRAINT)
        res = session.execute(stmt)
        if res.rowcount:
            created += 1
            try:
                from services.web_push_service import notify_meeting_soon_if_configured

                notify_meeting_soon_if_configured(
                    user_id=int(m.user_id),
                    meeting_id=mid,
                    title=title,
                    minutes_until=mins_left,
                    scheduled_at_iso=st.isoformat(),
                )
            except Exception as wp_exc:
                _log.debug("web_push meeting hook skipped: %s", wp_exc)
    return created


def run_meeting_reminder_scan() -> None:
    """Standalone + scheduler: one scan, log summary."""
    rid = new_request_id()
    factory = get_session_factory()
    if factory is None:
        log_event(rid, "meeting_reminder.scan", ok=False, extra={"reason": "no database"})
        return
    try:
        with session_scope() as session:
            n = notify_meeting_reminders_for_session(session, now=datetime.now(timezone.utc))
        log_event(rid, "meeting_reminder.scan", ok=True, extra={"notifications_created": n})
    except Exception as exc:
        _log.exception("meeting_reminder.scan_failed")
        log_event(rid, "meeting_reminder.scan", ok=False, error=str(exc))


def meeting_reminders_enabled() -> bool:
    return (os.getenv("THIRAMAI_ENABLE_MEETING_REMINDERS") or "1").strip().lower() in ("1", "true", "yes", "on")


def meeting_reminder_interval_seconds() -> int:
    try:
        s = int((os.getenv("THIRAMAI_MEETING_REMINDER_INTERVAL_SEC") or "60").strip())
    except ValueError:
        s = 60
    return max(30, min(s, 600))


def register_meeting_reminder_job(scheduler: Any) -> None:
    """Attach 30s–10m interval job to an existing APScheduler (typically alert_system)."""
    from apscheduler.triggers.interval import IntervalTrigger

    if not meeting_reminders_enabled():
        return
    sec = meeting_reminder_interval_seconds()
    scheduler.add_job(
        run_meeting_reminder_scan,
        IntervalTrigger(seconds=sec),
        id="thiramai_meeting_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    log_event(
        new_request_id(),
        "meeting_reminder.scheduler_job",
        ok=True,
        extra={"interval_seconds": sec},
    )
