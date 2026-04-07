"""
Aggregate **Personal OS + tenant snapshot** for ``GET /personal/today`` (tasks, reminders, low stock, sales).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from core.database import get_session_factory
from core.db.models import Habit, HabitLog, LearningLog, PersonalMission
from services.analytics_service import compute_dashboard_summary_sync, list_low_stock_alerts_sync
from services.life_os_service import MISSION_OPEN_STATUSES, list_upcoming_reminders


def build_personal_today_sync(
    *,
    user_id: int,
    organization_id: int,
    low_stock_threshold: int = 5,
    experience_limit: int = 5,
) -> dict[str, Any]:
    """
    Safe aggregate: empty personal slices when ``user_id <= 0``; business slices when ``organization_id > 0``.
    """
    now = datetime.now(timezone.utc).isoformat()
    uid = int(user_id)
    oid = int(organization_id)

    tasks_out: list[dict[str, Any]] = []
    reminders_out: list[dict[str, Any]] = []
    experiences_out: list[dict[str, Any]] = []
    habits_completed_today = 0
    tasks_completed_today = 0

    factory = get_session_factory()
    if factory is not None and uid > 0:
        with factory() as session:
            day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            habits_completed_today = int(
                session.execute(
                    select(func.count())
                    .select_from(HabitLog)
                    .join(Habit, HabitLog.habit_id == Habit.id)
                    .where(
                        Habit.user_id == uid,
                        HabitLog.completed_at >= day_start,
                        HabitLog.completed_at < day_end,
                    )
                ).scalar()
                or 0
            )
            tasks_completed_today = int(
                session.execute(
                    select(func.count())
                    .select_from(PersonalMission)
                    .where(
                        PersonalMission.user_id == uid,
                        ~PersonalMission.status.in_(tuple(MISSION_OPEN_STATUSES)),
                        PersonalMission.updated_at >= day_start,
                        PersonalMission.updated_at < day_end,
                    )
                ).scalar()
                or 0
            )
            stmt = (
                select(PersonalMission)
                .where(
                    PersonalMission.user_id == uid,
                    PersonalMission.status.in_(tuple(MISSION_OPEN_STATUSES)),
                )
                .order_by(PersonalMission.created_at.desc())
                .limit(30)
            )
            for m in session.execute(stmt).scalars().all():
                tasks_out.append(
                    {
                        "id": int(m.id),
                        "title": m.title,
                        "status": m.status,
                        "deadline": m.deadline.isoformat() if m.deadline else None,
                    }
                )
            for r in list_upcoming_reminders(session, uid, limit=15):
                reminders_out.append(
                    {
                        "id": int(r.id),
                        "title": r.title,
                        "remind_at": r.remind_at.isoformat() if r.remind_at else None,
                    }
                )

            if oid > 0:
                ex_stmt = (
                    select(LearningLog)
                    .where(LearningLog.organization_id == oid)
                    .order_by(LearningLog.created_at.desc())
                    .limit(max(1, min(experience_limit, 50)))
                )
                for row in session.execute(ex_stmt).scalars().all():
                    experiences_out.append(
                        {
                            "id": int(row.id),
                            "outcome": row.outcome,
                            "action_type": row.action_type,
                            "lesson_summary": (row.lesson_summary or "")[:500],
                            "created_at": row.created_at.isoformat() if row.created_at else None,
                        }
                    )

    low_stock: dict[str, Any] = {"ok": True, "items": [], "count": 0}
    sales: dict[str, Any] = {"ok": False}
    if oid > 0:
        low_stock = list_low_stock_alerts_sync(oid, threshold=low_stock_threshold, limit=40)
        sales = compute_dashboard_summary_sync(oid, low_stock_threshold=low_stock_threshold)

    return {
        "ok": True,
        "as_of_utc": now,
        "user_id": uid,
        "organization_id": oid,
        "tasks": tasks_out,
        "reminders": reminders_out,
        "experiences": experiences_out,
        "low_stock": low_stock,
        "today_sales": sales,
        "habits_completed_today": habits_completed_today,
        "tasks_completed_today": tasks_completed_today,
    }
