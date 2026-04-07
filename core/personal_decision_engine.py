"""
Personal decision layer — rank tasks by impact, suggest next move, balance life vs business cues.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.calendar_engine import suggest_best_time, workload_level


def _parse_iso_dt(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _impact_score(
    task: dict[str, Any],
    *,
    org_active: bool,
    low_stock_skus: set[str],
) -> float:
    title = str(task.get("title") or "").lower()
    dl = _parse_iso_dt(task.get("deadline"))
    score = 5.0
    if dl is not None:
        now = datetime.now(timezone.utc)
        if dl < now:
            score += 40
        else:
            hours = (dl - now).total_seconds() / 3600.0
            if hours < 24:
                score += 25
            elif hours < 72:
                score += 15
    if org_active:
        for sku_fragment in low_stock_skus:
            if sku_fragment and sku_fragment.lower() in title:
                score += 12
        if any(k in title for k in ("stock", "inventory", "invoice", "gst", "sale", "customer")):
            score += 6
    else:
        if any(k in title for k in ("health", "family", "learn", "exercise", "habit")):
            score += 8
    st = str(task.get("status") or "").lower()
    if st == "in_progress":
        score += 4
    return score


def prioritize_tasks(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Ordered list with ``mission_id``, ``title``, ``impact``, ``lane`` (personal|business|mixed).
    """
    tasks = snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else []
    low = snapshot.get("low_stock") if isinstance(snapshot.get("low_stock"), dict) else {}
    items = low.get("items") if isinstance(low.get("items"), list) else []
    skus = set()
    for it in items[:15]:
        if isinstance(it, dict):
            s = str(it.get("sku_name") or "").strip()
            if s:
                skus.add(s[:40])
    oid = int(snapshot.get("organization_id") or 0)
    org_active = oid > 0

    ranked: list[tuple[float, dict[str, Any]]] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        mid = int(t.get("id") or 0)
        title = str(t.get("title") or "")[:200]
        imp = _impact_score(t, org_active=org_active, low_stock_skus=skus)
        title_l = title.lower()
        lane = "personal"
        if org_active and any(k in title_l for k in ("sale", "stock", "invoice", "customer", "inventory")):
            lane = "business"
        elif org_active and any(k in title_l for k in ("report", "team", "payroll")):
            lane = "mixed"
        ranked.append(
            (
                imp,
                {
                    "mission_id": mid if mid > 0 else None,
                    "title": title,
                    "impact": round(imp, 1),
                    "lane": lane,
                    "deadline": t.get("deadline"),
                },
            )
        )
    ranked.sort(key=lambda x: -x[0])
    return [x[1] for x in ranked[:20]]


def suggest_next_move(snapshot: dict[str, Any], priority_tasks: list[dict[str, Any]]) -> str:
    """Single line director cue."""
    if not priority_tasks:
        return "Queue is clear — capture one goal or enjoy a planning window."
    top = priority_tasks[0]
    slot = suggest_best_time(
        tasks=snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else [],
        reminders=snapshot.get("reminders") if isinstance(snapshot.get("reminders"), list) else [],
        task_duration_min=30,
    )
    title = str(top.get("title") or "your top task")[:72]
    if slot.get("ok"):
        return f"Next: «{title}» — use the next open calendar block for a focused pass."
    return f"Next: «{title}» — even a 20-minute slice moves the day."


def balance_personal_business(snapshot: dict[str, Any], priority_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    oid = int(snapshot.get("organization_id") or 0)
    if oid <= 0:
        return {"blend": "personal_focus", "tip": "Personal lane — protect energy for habits and missions."}
    counts = {"personal": 0, "business": 0, "mixed": 0}
    for p in priority_tasks[:10]:
        lane = str(p.get("lane") or "personal")
        counts[lane] = counts.get(lane, 0) + 1
    if counts["business"] >= counts["personal"] + 2:
        tip = "Business-heavy list — slot one personal maintenance item so the week stays sustainable."
        blend = "business_heavy"
    elif counts["personal"] >= counts["business"] + 2:
        tip = "Personal-heavy — if the org is active, one business touch today keeps parity."
        blend = "personal_heavy"
    else:
        tip = "Balanced mix — alternate lanes by energy blocks."
        blend = "balanced"
    return {"blend": blend, "tip": tip, "counts": counts}


def decision_bundle(snapshot: dict[str, Any]) -> dict[str, Any]:
    pts = prioritize_tasks(snapshot)
    return {
        "priority_tasks": pts,
        "next_best_move": suggest_next_move(snapshot, pts),
        "balance": balance_personal_business(snapshot, pts),
        "workload": workload_level(
            len(snapshot.get("tasks") or []),
            len(snapshot.get("reminders") or []),
        ),
    }
