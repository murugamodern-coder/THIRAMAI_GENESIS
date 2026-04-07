"""
Personal life context mode (time-of-day, workload) for Personal AI Director — not the council vault engine.
"""

from __future__ import annotations

from typing import Any

from core.calendar_engine import workload_level


def resolve_life_mode(
    snapshot: dict[str, Any],
    *,
    hour_utc: int | None = None,
    engagement_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Returns ``mode`` in ``focus`` | ``rest`` | ``push`` | ``reflect`` plus human-readable hints.
    """
    tasks = snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else []
    reminders = snapshot.get("reminders") if isinstance(snapshot.get("reminders"), list) else []
    daily_score = int(snapshot.get("daily_score") or 0)
    habits_done = int(snapshot.get("habits_completed_today") or 0)
    tasks_done = int(snapshot.get("tasks_completed_today") or 0)

    h = hour_utc
    if h is None:
        raw = snapshot.get("jarvis_hour_utc")
        if isinstance(raw, int):
            h = max(0, min(23, raw))
        else:
            from datetime import datetime, timezone

            h = datetime.now(timezone.utc).hour

    wl = workload_level(len(tasks), len(reminders))
    ex = engagement_extra if isinstance(engagement_extra, dict) else {}
    actions_block = ex.get("actions_today") if isinstance(ex.get("actions_today"), dict) else {}
    actions_today = int(actions_block.get("count") or 0)

    if h >= 22 or h < 5:
        mode = "rest"
        reason = "Late or very early UTC — favor wind-down or gentle planning."
    elif 5 <= h < 9:
        mode = "reflect" if len(tasks) > 5 else "focus"
        reason = "Morning — sketch intent then anchor one concrete move."
    elif 9 <= h < 12:
        mode = "focus"
        reason = "Mid-morning — protect deep focus blocks."
    elif 12 <= h < 15:
        mode = "push" if wl in ("heavy", "moderate") else "focus"
        reason = "Midday — execute or push through operational load."
    elif 15 <= h < 19:
        mode = "push" if wl == "heavy" else "focus"
        reason = "Afternoon — close loops before context switches."
    else:
        mode = "reflect"
        reason = "Evening — review, gratitude, light planning."

    if daily_score < 40 and len(tasks) >= 4:
        mode = "push"
        reason = "Score lagging with backlog — short push window recommended."

    if tasks_done + habits_done + actions_today >= 5 and wl != "heavy":
        if mode == "push":
            mode = "reflect"
            reason = "Solid activity already — shift to reflect and consolidate."

    return {
        "mode": mode,
        "reason": reason,
        "hour_utc": h,
        "workload_band": wl,
        "signals": {
            "open_tasks": len(tasks),
            "upcoming_reminders": len(reminders),
            "daily_score": daily_score,
            "actions_today": actions_today,
        },
    }


def build_life_context(
    snapshot: dict[str, Any],
    calendar_summary: dict[str, Any],
    *,
    engagement_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merged object for API ``life_context``."""
    mode_block = resolve_life_mode(snapshot, engagement_extra=engagement_extra)
    return {
        "mode": mode_block["mode"],
        "mode_reason": mode_block["reason"],
        "calendar": calendar_summary,
        "signals": mode_block["signals"],
    }
