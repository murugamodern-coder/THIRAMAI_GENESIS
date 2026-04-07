"""
Smart calendar-style scheduling hints from tasks and reminders (pure logic, no external APIs).

Assumes a simple **work band** in local interpretation: uses UTC hour from context for consistency
with the rest of Personal OS; clients may shift mentally by timezone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

WORK_START_H = 8
WORK_END_H = 20
DEFAULT_BLOCK_MIN = 30
OVERLOAD_TASK_THRESHOLD = 8


def _parse_iso_dt(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        raw = s.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def workload_level(n_tasks: int, n_reminders: int) -> str:
    load = n_tasks + (n_reminders // 2)
    if load >= OVERLOAD_TASK_THRESHOLD:
        return "heavy"
    if load >= 4:
        return "moderate"
    if load >= 1:
        return "light"
    return "clear"


def avoid_overload(n_tasks: int, n_reminders: int) -> bool:
    """True if user should defer new commitments."""
    return workload_level(n_tasks, n_reminders) == "heavy"


def free_time_slots(
    *,
    tasks: list[dict[str, Any]],
    reminders: list[dict[str, Any]],
    day_start_utc: datetime | None = None,
    work_start_h: int = WORK_START_H,
    work_end_h: int = WORK_END_H,
    block_minutes: int = DEFAULT_BLOCK_MIN,
) -> list[dict[str, Any]]:
    """
    Return coarse free windows (UTC day) by carving out reminder times as busy anchors.
    """
    now = day_start_utc or datetime.now(timezone.utc)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)

    busy: list[tuple[datetime, datetime]] = []
    for r in reminders:
        dt = _parse_iso_dt(r.get("remind_at"))
        if dt is None:
            continue
        busy.append((dt - timedelta(minutes=15), dt + timedelta(minutes=30)))

    busy.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    for a, b in busy:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    slots: list[dict[str, Any]] = []
    cursor = day0.replace(hour=work_start_h, minute=0, second=0, microsecond=0)
    end_band = day0.replace(hour=work_end_h, minute=0, second=0, microsecond=0)

    for a, b in merged:
        if a > cursor and (a - cursor) >= timedelta(minutes=block_minutes):
            slots.append(
                {
                    "start": cursor.isoformat(),
                    "end": a.isoformat(),
                    "minutes": int((a - cursor).total_seconds() // 60),
                }
            )
        cursor = max(cursor, b)

    if end_band > cursor and (end_band - cursor) >= timedelta(minutes=block_minutes):
        slots.append(
            {
                "start": cursor.isoformat(),
                "end": end_band.isoformat(),
                "minutes": int((end_band - cursor).total_seconds() // 60),
            }
        )

    return slots[:12]


def suggest_best_time(
    *,
    tasks: list[dict[str, Any]],
    reminders: list[dict[str, Any]],
    task_duration_min: int = 45,
) -> dict[str, Any]:
    """Pick the first free slot that fits ``task_duration_min``."""
    slots = free_time_slots(tasks=tasks, reminders=reminders)
    for s in slots:
        if int(s.get("minutes") or 0) >= task_duration_min:
            return {
                "ok": True,
                "start": s["start"],
                "end": s["end"],
                "reason": "First open window after reminder anchors.",
            }
    return {
        "ok": False,
        "start": None,
        "end": None,
        "reason": "No clean block today — try a 20-minute micro-sprint or defer one reminder.",
    }


def auto_schedule_tasks(
    tasks: list[dict[str, Any]],
    reminders: list[dict[str, Any]],
    *,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """
    Order tasks by deadline proximity then propose sequential placeholder times from free slots.
    """
    enriched: list[tuple[datetime | None, dict[str, Any]]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        dl = _parse_iso_dt(t.get("deadline"))
        enriched.append((dl, t))
    _far = datetime(2099, 1, 1, tzinfo=timezone.utc)
    enriched.sort(key=lambda x: (x[0] is None, x[0] if x[0] is not None else _far))

    slots = free_time_slots(tasks=tasks, reminders=reminders)
    slot_idx = 0
    acc_start = _parse_iso_dt(slots[0]["start"]) if slots else None
    out: list[dict[str, Any]] = []

    for _, t in enriched[:max_items]:
        tid = int(t.get("id") or 0)
        title = str(t.get("title") or "")[:200]
        proposed_start = None
        proposed_end = None
        if acc_start and slot_idx < len(slots):
            proposed_start = acc_start.isoformat()
            acc_start = acc_start + timedelta(minutes=DEFAULT_BLOCK_MIN)
            proposed_end = acc_start.isoformat()
            if slot_idx < len(slots):
                slot_end = _parse_iso_dt(slots[slot_idx].get("end"))
                if slot_end and acc_start > slot_end - timedelta(minutes=15):
                    slot_idx += 1
                    if slot_idx < len(slots):
                        acc_start = _parse_iso_dt(slots[slot_idx].get("start")) or acc_start
        out.append(
            {
                "mission_id": tid if tid > 0 else None,
                "title": title,
                "proposed_start_utc": proposed_start,
                "proposed_end_utc": proposed_end,
                "block_minutes": DEFAULT_BLOCK_MIN,
            }
        )

    return out


def calendar_summary(context: dict[str, Any]) -> dict[str, Any]:
    """Bundle for API / director."""
    tasks = context.get("tasks") if isinstance(context.get("tasks"), list) else []
    reminders = context.get("reminders") if isinstance(context.get("reminders"), list) else []
    wl = workload_level(len(tasks), len(reminders))
    best = suggest_best_time(tasks=tasks, reminders=reminders)
    return {
        "workload_band": wl,
        "overload": avoid_overload(len(tasks), len(reminders)),
        "free_slots_preview": len(free_time_slots(tasks=tasks, reminders=reminders)),
        "suggested_focus_slot": best,
        "auto_scheduled": auto_schedule_tasks(tasks, reminders, max_items=5),
    }
