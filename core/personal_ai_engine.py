"""
Personal daily AI guidance — deterministic, actionable suggestions (API + UI hints).

Outputs **priority tiers**, **structured actionable_suggestions**, and string aliases for older clients.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_STRONG_ACTIONS = 3
MAX_ALERTS_SHOWN = 8


def _utc_hour_from_context(context: dict[str, Any]) -> int:
    raw = context.get("jarvis_hour_utc")
    if isinstance(raw, int):
        return max(0, min(23, raw))
    return datetime.now(timezone.utc).hour


def _time_mode(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _tone_for_mode(
    time_mode: str,
    *,
    n_tasks: int,
    daily_score: int,
    rev_num: float | None,
) -> str:
    if time_mode == "evening" or time_mode == "night":
        return "warm"
    if daily_score >= 75 and (n_tasks == 0 or (rev_num is not None and rev_num > 0)):
        return "motivational"
    if time_mode == "morning":
        return "motivational"
    return "steady"


def _task_title_by_id(tasks: list[dict[str, Any]], mission_id: int) -> str:
    mid = int(mission_id)
    for t in tasks:
        if int(t.get("id") or 0) == mid:
            return str(t.get("title") or "").strip()
    return ""


def _derive_focus_lock(
    actionable: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    for a in actionable:
        if not isinstance(a, dict):
            continue
        act = str(a.get("action") or "").strip().lower()
        body = a.get("body") if isinstance(a.get("body"), dict) else {}
        if act == "complete_task":
            mid = body.get("mission_id")
            if mid is not None and int(mid) > 0:
                title = _task_title_by_id(tasks, int(mid)) or (a.get("text") or "your top task")[:80]
                return (
                    f"Today's anchor: «{title}»",
                    {"mission_id": int(mid), "title": title, "sku": None},
                )
        if act == "restock":
            sku = str(body.get("item") or "").strip()
            if sku:
                t_short = f"Restock {sku}"
                return (
                    f"Today's anchor: {t_short}",
                    {"mission_id": None, "title": t_short, "sku": sku},
                )
        if act == "record_sale":
            return (
                "Today's anchor: log today's sales",
                {"mission_id": None, "title": "Record a sale", "sku": None},
            )
    if tasks:
        t0 = tasks[0]
        mid = int(t0.get("id") or 0)
        title = str(t0.get("title") or "next task").strip()[:120]
        if title:
            return (
                f"Today's anchor: «{title}»",
                {"mission_id": mid if mid > 0 else None, "title": title, "sku": None},
            )
    return "", None


def _encouragement_line(
    *,
    n_tasks: int,
    streak_days: int,
    daily_score: int,
    rev_num: float | None,
    time_mode: str,
) -> str:
    if daily_score >= 80:
        return "Great job — you're showing up consistently."
    if n_tasks == 0 and (rev_num is None or rev_num > 0):
        if daily_score >= 70:
            return "Great job completing tasks 🔥"
        return "Clean queue — nice work staying on top of things."
    if streak_days >= 5:
        return f"🔥 {streak_days}-day streak — that discipline adds up."
    if n_tasks in (1, 2, 3):
        return "You can finish one more today — small wins compound."
    if time_mode == "evening" and n_tasks > 0:
        return "Be kind to yourself; even one closed loop is a win."
    if time_mode == "morning":
        return "Fresh start — pick one thing and ride the momentum."
    return "I'm here with you — we'll keep this light and useful."


def _time_nudge(time_mode: str, n_rem: int, n_tasks: int) -> str:
    if time_mode == "morning":
        return "Morning mode: sketch the day, then one concrete move."
    if time_mode == "afternoon":
        if n_rem > 0:
            return "Afternoon pulse: glance at reminders so nothing slips."
        return "Afternoon nudge: clear one nagging item before you switch contexts."
    if time_mode == "evening":
        return "Evening tone: wrap calmly — tomorrow can pick up the rest."
    return "Night owl or early wind-down — keep hydration and one deep breath."


def _adapt_top_focus_time(top_focus: str, time_mode: str) -> str:
    if not top_focus:
        return top_focus
    tags = {
        "morning": "Morning • ",
        "afternoon": "Afternoon • ",
        "evening": "Evening • ",
        "night": "Night • ",
    }
    tag = tags.get(time_mode, "")
    if not tag:
        return top_focus
    if top_focus.startswith(tag.strip()):
        return top_focus
    return tag + top_focus


def _memory_score_item(item: dict[str, Any], memory: dict[str, Any] | None) -> float:
    if not memory or not isinstance(item, dict):
        return 0.0
    act = str(item.get("action") or "").strip().lower()
    text = str(item.get("text") or "").lower()
    score = 0.0
    boost_a = memory.get("boost_actions") if isinstance(memory.get("boost_actions"), dict) else {}
    sup_a = memory.get("suppress_actions") if isinstance(memory.get("suppress_actions"), dict) else {}
    score += float(boost_a.get(act, 0)) * 0.35
    score -= float(sup_a.get(act, 0)) * 0.55
    for ph in memory.get("boost_phrases") or []:
        if isinstance(ph, str) and len(ph) >= 4 and ph.lower() in text:
            score += 1.2
    for ph in memory.get("suppress_phrases") or []:
        if isinstance(ph, str) and len(ph) >= 4 and ph.lower() in text:
            score -= 2.0
    return score


def _apply_memory_ranking(
    actionable: list[dict[str, Any]],
    memory: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not actionable or not memory:
        return actionable
    indexed = list(enumerate(actionable))
    indexed.sort(key=lambda pair: (-_memory_score_item(pair[1], memory), pair[0]))
    return [pair[1] for pair in indexed]


def _parse_today_revenue(sales: Any) -> tuple[float | None, str]:
    if not isinstance(sales, dict) or not sales.get("ok"):
        return None, ""
    block = sales.get("revenue_inr") if isinstance(sales.get("revenue_inr"), dict) else {}
    raw = block.get("today")
    if raw is None:
        return None, ""
    s = str(raw).strip().replace("₹", "").replace(",", "")
    if s in ("", "—", "-", "n/a", "N/A"):
        return 0.0, str(raw)
    try:
        return float(s), str(raw)
    except ValueError:
        return None, str(raw)


def _sug(
    text: str,
    action: str,
    action_type: str,
    endpoint: str,
    *,
    method: str = "POST",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "text": text,
        "action": action,
        "action_type": action_type,
        "endpoint": endpoint,
    }
    if method:
        out["method"] = method
    if body is not None:
        out["body"] = body
    return out


def generate_daily_guidance(
    context: dict[str, Any],
    *,
    memory: dict[str, Any] | None = None,
    followups: list[str] | None = None,
) -> dict[str, Any]:
    """
    Returns:
    - ``top_focus`` — single headline
    - ``secondary`` / ``low_priority`` — priority strings
    - ``alerts`` — alert strings
    - ``actionable_suggestions`` — dicts with text, action, action_type, endpoint, optional method/body
    - ``suggestions`` — list of text only (backward compatible)
    - ``focus`` — same as ``top_focus`` (backward compatible)
    - ``followups`` — accountability lines from yesterday's snapshot (when provided)
    - ``memory_hint`` — short learner summary when ``memory`` is passed
    - ``focus_lock`` / ``focus_lock_target`` — one main thread + persistence hint
    - ``message`` / ``tone`` / ``time_mode`` — human voice layer
    """
    tasks = context.get("tasks") if isinstance(context.get("tasks"), list) else []
    reminders = context.get("reminders") if isinstance(context.get("reminders"), list) else []
    low_stock = context.get("low_stock") if isinstance(context.get("low_stock"), dict) else {}
    sales = context.get("today_sales") or context.get("sales") or {}
    if not isinstance(sales, dict):
        sales = {}

    auth = bool(context.get("authenticated"))
    uid = int(context.get("user_id") or 0)
    oid = int(context.get("organization_id") or 0)
    hour = _utc_hour_from_context(context)
    tmode = _time_mode(hour)
    daily_score = int(context.get("daily_score") or 0)
    streak_days = int(context.get("streak_days") or 0)

    alerts: list[str] = []
    actionable: list[dict[str, Any]] = []
    secondary: list[str] = []
    low_priority: list[str] = []

    rev_num, rev_display = _parse_today_revenue(sales)

    if not auth or uid <= 0:
        top = "Sign in to sync your day — tasks, stock, and sales in one place."
        alerts.append("Not signed in — personal and business hints stay offline.")
        actionable.append(
            _sug(
                "Open login and save your session",
                "sign_in",
                "ui",
                "/",
                method="GET",
                body=None,
            )
        )
        fu = list(followups or [])[:8]
        if fu:
            alerts = fu + alerts
        enc = "Whenever you're ready, I'm here — no pressure."
        msg = f"{enc} One login unlocks your full assistant."
        return _pack_guidance(
            top_focus=top,
            secondary=["Connect once to unlock actions and scoring."],
            low_priority=["Enterprise tools stay under Command deck when you need them."],
            alerts=alerts[:MAX_ALERTS_SHOWN],
            actionable=actionable,
            followups=fu,
            memory=memory,
            focus_lock="",
            focus_lock_target=None,
            message=msg,
            tone="warm",
            time_mode=tmode,
            encouragement=enc,
        )

    n_tasks = len(tasks)
    n_rem = len(reminders)
    stock_items = low_stock.get("items") if isinstance(low_stock.get("items"), list) else []
    n_low = int(low_stock.get("count") or len(stock_items))

    # --- Top focus ---
    if oid > 0 and n_low > 0:
        sku0 = (stock_items[0].get("sku_name") or "item").strip()
        top_focus = f"Priority: low stock on {sku0} — restock or verify counts first."
    elif oid > 0 and rev_num is not None and rev_num <= 0:
        top_focus = "Priority: no sales logged today — close one sale or log revenue."
    elif n_tasks > 0:
        top_focus = f"Priority: {n_tasks} open task(s) — finish the smallest one next."
    elif n_rem > 0:
        top_focus = f"Priority: upcoming reminder — {((reminders[0].get('title') or 'task') or '').strip()}."
    else:
        top_focus = "Good moment for planning or one deep-work block."

    top_focus = _adapt_top_focus_time(top_focus, tmode)

    # --- Alerts ---
    if oid > 0 and n_low > 0:
        for it in stock_items[:3]:
            sku = (it.get("sku_name") or "Item").strip()
            q = it.get("quantity")
            alerts.append(f"Low stock: {sku} (qty {q}).")
    if n_rem > 0:
        nxt = reminders[0]
        alerts.append(f"Upcoming: {(nxt.get('title') or 'Reminder').strip()}")
    if oid > 0 and rev_num is not None and rev_num <= 0:
        alerts.append("No sales recorded today yet.")
    if n_tasks >= 5:
        alerts.append(f"{n_tasks} open tasks — trim or complete three.")

    # --- Secondary / low priority narrative ---
    if n_tasks and n_tasks < 5:
        secondary.append(f"{n_tasks} mission(s) still open.")
    if oid > 0 and rev_num is not None and rev_num > 0 and rev_display:
        secondary.append(f"Sales today: {rev_display}.")
    low_priority.append("Review Research tab when you need market intel.")
    if not n_low and oid > 0:
        low_priority.append("Stock levels look OK at this threshold.")

    # --- Actionable suggestions ---
    if oid > 0 and rev_num is not None and rev_num <= 0:
        actionable.append(
            _sug(
                "Record a sale in POS",
                "record_sale",
                "ui",
                "/dashboard",
                body={"action": "record_sale"},
            )
        )

    if n_tasks > 0:
        k = min(3, n_tasks)
        first = tasks[0]
        mid = int(first.get("id") or 0)
        title_snip = (first.get("title") or "next task")[:80]
        if mid > 0:
            actionable.append(
                _sug(
                    f"Complete {k} task(s) — start with: {title_snip}",
                    "complete_task",
                    "api_call",
                    "/personal/action",
                    body={"action": "complete_task", "mission_id": mid},
                )
            )
        else:
            actionable.append(
                _sug(
                    f"Work through {k} task(s) — start with: {title_snip}",
                    "open_tasks",
                    "ui",
                    "/",
                    method="GET",
                    body={"action": "open_life_os"},
                )
            )

    for it in stock_items[:2]:
        sku = (it.get("sku_name") or "").strip()
        if not sku:
            continue
        actionable.append(
            _sug(
                f"Restock {sku}",
                "restock",
                "api_call",
                "/personal/action",
                body={"action": "restock", "item": sku, "quantity": 10},
            )
        )

    if not actionable and n_rem > 0:
        actionable.append(
            _sug("Clear the next reminder", "open_tasks", "ui", "/", body={"action": "open_life_os"})
        )

    if n_tasks == 0 and n_low == 0 and (rev_num is None or rev_num > 0):
        actionable.append(
            _sug("Light queue — open Command deck only if needed", "open_pos", "ui", "/dashboard", body={})
        )

    actionable = _apply_memory_ranking(actionable, memory)
    actionable = actionable[:MAX_STRONG_ACTIONS]
    fu = list(followups or [])[:8]
    if fu:
        alerts = fu + alerts

    focus_lock_str, focus_meta = _derive_focus_lock(actionable, tasks)
    enc = _encouragement_line(
        n_tasks=n_tasks,
        streak_days=streak_days,
        daily_score=daily_score,
        rev_num=rev_num,
        time_mode=tmode,
    )
    tn = _time_nudge(tmode, n_rem, n_tasks)
    if focus_lock_str:
        msg = f"{enc} {focus_lock_str} {tn}"
    else:
        msg = f"{enc} {tn}"
    tone = _tone_for_mode(tmode, n_tasks=n_tasks, daily_score=daily_score, rev_num=rev_num)

    return _pack_guidance(
        top_focus=top_focus,
        secondary=secondary[:8],
        low_priority=low_priority[:8],
        alerts=alerts[:MAX_ALERTS_SHOWN],
        actionable=actionable,
        followups=fu,
        memory=memory,
        focus_lock=focus_lock_str,
        focus_lock_target=focus_meta,
        message=msg,
        tone=tone,
        time_mode=tmode,
        encouragement=enc,
    )


def _pack_guidance(
    *,
    top_focus: str,
    secondary: list[str],
    low_priority: list[str],
    alerts: list[str],
    actionable: list[dict[str, Any]],
    followups: list[str] | None = None,
    memory: dict[str, Any] | None = None,
    focus_lock: str = "",
    focus_lock_target: dict[str, Any] | None = None,
    message: str = "",
    tone: str = "steady",
    time_mode: str = "morning",
    encouragement: str = "",
) -> dict[str, Any]:
    texts = [a.get("text", "") for a in actionable if isinstance(a, dict) and a.get("text")]
    out: dict[str, Any] = {
        "top_focus": top_focus,
        "secondary": secondary,
        "low_priority": low_priority,
        "focus": top_focus,
        "alerts": alerts,
        "actionable_suggestions": actionable,
        "suggestions": texts,
        "followups": list(followups or []),
        "focus_lock": focus_lock or "",
        "focus_lock_target": focus_lock_target,
        "message": message,
        "tone": tone,
        "time_mode": time_mode,
    }
    if encouragement:
        out["encouragement"] = encouragement
    if memory and isinstance(memory.get("preferred_summary"), str):
        out["memory_hint"] = memory["preferred_summary"]
    return out


def generate_evening_summary(context: dict[str, Any]) -> dict[str, Any]:
    g = generate_daily_guidance(context)
    tasks = context.get("tasks") if isinstance(context.get("tasks"), list) else []
    reminders = context.get("reminders") if isinstance(context.get("reminders"), list) else []
    low_stock = context.get("low_stock") if isinstance(context.get("low_stock"), dict) else {}
    sales = context.get("today_sales") or context.get("sales") or {}
    if not isinstance(sales, dict):
        sales = {}

    rev_num, rev_display = _parse_today_revenue(sales)
    stock_items = low_stock.get("items") if isinstance(low_stock.get("items"), list) else []
    n_low = int(low_stock.get("count") or len(stock_items))
    tmode = _time_mode(_utc_hour_from_context(context))

    wins: list[str] = []
    carry_over: list[str] = []

    if rev_num is not None and rev_num > 0:
        wins.append(f"Revenue today: {rev_display or rev_num}.")

    if len(tasks) == 0:
        wins.append("No open missions — clean slate or a quiet day.")
    else:
        carry_over.append(f"{len(tasks)} task(s) still open.")

    if n_low > 0:
        carry_over.append(f"{n_low} SKU(s) below stock threshold.")

    if reminders:
        carry_over.append(f"{len(reminders)} upcoming reminder(s).")

    headline = g.get("top_focus") or g.get("focus") or "Day wrap-up."
    summary_parts = [headline]
    if wins:
        summary_parts.append("Wins: " + " ".join(wins[:3]))
    if carry_over:
        summary_parts.append("Carry forward: " + " ".join(carry_over[:3]))

    if tmode in ("evening", "night"):
        tomorrow = (
            "Evening wrap: be proud of what moved. Tomorrow we pick one gentle priority together."
        )
    elif not stock_items and len(tasks) <= 1:
        tomorrow = "Tomorrow: block a little focus time and peek at reminders — I'll nudge kindly."
    else:
        tomorrow = "Tomorrow: one concrete move before noon, then your top task — you've got this."

    return {
        "summary": " ".join(summary_parts),
        "wins": wins[:8],
        "carry_over": carry_over[:8],
        "tomorrow_hint": tomorrow,
        "focus_echo": headline,
        "voice_tone": g.get("tone"),
        "companion_message": g.get("message"),
    }


def merge_director_into_guidance(guidance: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    """
    Attach Personal AI Director fields (``memory_based_suggestions``, ``director_mode``,
    ``next_best_move``, etc.) to the guidance dict. Delegates to ``core.personal_director``.
    """
    from core.personal_director import apply_director_enrichment_to_guidance

    return apply_director_enrichment_to_guidance(guidance, enrichment)
