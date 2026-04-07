"""
Proactive signals — missed deadlines, heavy queues, business risk — as prioritized alerts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

PRIORITY_CRITICAL = 1
PRIORITY_HIGH = 2
PRIORITY_MEDIUM = 3
PRIORITY_LOW = 4
PRIORITY_INFO = 5


def _parse_iso_dt(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_proactive_alerts(snapshot: dict[str, Any], *, engagement_extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Returns alerts sorted by priority (ascending = more urgent).
    Each item: ``priority``, ``code``, ``message``, ``hint``.
    """
    tasks = snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else []
    reminders = snapshot.get("reminders") if isinstance(snapshot.get("reminders"), list) else []
    low_stock = snapshot.get("low_stock") if isinstance(snapshot.get("low_stock"), dict) else {}
    sales = snapshot.get("today_sales") or snapshot.get("sales") or {}
    if not isinstance(sales, dict):
        sales = {}
    uid = int(snapshot.get("user_id") or 0)
    oid = int(snapshot.get("organization_id") or 0)
    authed = bool(snapshot.get("authenticated"))
    daily_score = int(snapshot.get("daily_score") or 0)
    habits_done = int(snapshot.get("habits_completed_today") or 0)
    tasks_done = int(snapshot.get("tasks_completed_today") or 0)

    ex = engagement_extra if isinstance(engagement_extra, dict) else {}
    actions_block = ex.get("actions_today") if isinstance(ex.get("actions_today"), dict) else {}
    actions_today = int(actions_block.get("count") or 0)

    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    if authed and uid > 0 and daily_score < 35 and len(tasks) >= 3:
        alerts.append(
            {
                "priority": PRIORITY_MEDIUM,
                "code": "low_momentum",
                "message": "Momentum is low with several open tasks — one 15-minute win will move the score.",
                "hint": "complete_smallest_task",
            }
        )

    if authed and uid > 0 and len(tasks) >= 1 and tasks_done == 0 and habits_done == 0 and actions_today == 0:
        alerts.append(
            {
                "priority": PRIORITY_LOW,
                "code": "light_activity_today",
                "message": "No completed tasks or habits logged yet today — optional reset with one tiny action.",
                "hint": "log_one_habit_or_task",
            }
        )

    for t in tasks:
        if not isinstance(t, dict):
            continue
        dl = _parse_iso_dt(t.get("deadline"))
        if dl is None:
            continue
        if dl < now:
            title = str(t.get("title") or "Task")[:80]
            alerts.append(
                {
                    "priority": PRIORITY_HIGH,
                    "code": "missed_deadline",
                    "message": f"Overdue: «{title}» — reschedule or close the loop.",
                    "hint": "reschedule_or_complete",
                    "mission_id": int(t.get("id") or 0) or None,
                }
            )

    if len(tasks) >= 8:
        alerts.append(
            {
                "priority": PRIORITY_MEDIUM,
                "code": "task_overload",
                "message": f"{len(tasks)} open tasks — trim or batch to avoid overload.",
                "hint": "calendar_triage",
            }
        )

    for r in reminders[:5]:
        if not isinstance(r, dict):
            continue
        ra = _parse_iso_dt(r.get("remind_at"))
        if ra is None:
            continue
        if now <= ra <= now + timedelta(hours=8):
            title = str(r.get("title") or "Reminder")[:80]
            alerts.append(
                {
                    "priority": PRIORITY_HIGH,
                    "code": "reminder_soon",
                    "message": f"Upcoming reminder: {title}",
                    "hint": "prepare_context",
                    "reminder_id": int(r.get("id") or 0) or None,
                }
            )

    items = low_stock.get("items") if isinstance(low_stock.get("items"), list) else []
    n_low = int(low_stock.get("count") or len(items))
    if oid > 0 and n_low > 0:
        sku = ""
        if items and isinstance(items[0], dict):
            sku = str(items[0].get("sku_name") or "").strip()[:60]
        alerts.append(
            {
                "priority": PRIORITY_CRITICAL if n_low >= 3 else PRIORITY_HIGH,
                "code": "low_stock",
                "message": f"Low stock on {n_low} SKU(s)" + (f" — first: {sku}" if sku else ""),
                "hint": "restock",
            }
        )

    rev_ok = isinstance(sales, dict) and sales.get("ok")
    rev_block = sales.get("revenue_inr") if isinstance(sales.get("revenue_inr"), dict) else {}
    raw = rev_block.get("today")
    if oid > 0 and rev_ok and raw is not None:
        try:
            rev_num = float(str(raw).replace(",", "").replace("₹", "").strip() or "0")
        except ValueError:
            rev_num = None
        else:
            if rev_num is not None and rev_num <= 0:
                alerts.append(
                    {
                        "priority": PRIORITY_MEDIUM,
                        "code": "no_revenue_today",
                        "message": "No revenue logged today — close one sale or record cash flow.",
                        "hint": "record_sale",
                    }
                )

    alerts.sort(key=lambda a: (int(a.get("priority") or 99), a.get("code") or ""))
    return alerts[:16]
