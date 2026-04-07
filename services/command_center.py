"""
Master Command Center: unified ops view (analytics + inventory + pending work) + AI priority tiers.

Priority labels (for UX / orchestrator):
  🔴 Emergency — stock-outs, missed statutory windows (heuristic), missed dated meetings
  🟠 Urgent — low stock, filing windows, pending high-risk HITL, meetings within 48h
  🟡 Later — reminders and non-blocking items

GST hints are **heuristic** (typical monthly GSTR-1 ~11th, GSTR-3B ~20th); not legal advice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

import executive_core

from services.analytics_service import compute_dashboard_summary_sync, list_low_stock_alerts_sync
from services.business_snapshot_service import build_business_snapshot
from services.inventory_alerts import get_inventory_alerts
from services.pending_tasks import list_open_agenda_tasks, list_pending_hitl


class PriorityTier(str, Enum):
    emergency = "emergency"
    urgent = "urgent"
    later = "later"


EMOJI = {
    PriorityTier.emergency: "🔴",
    PriorityTier.urgent: "🟠",
    PriorityTier.later: "🟡",
}

LABEL = {
    PriorityTier.emergency: "Emergency",
    PriorityTier.urgent: "Urgent",
    PriorityTier.later: "Later",
}


@dataclass
class PriorityItem:
    tier: PriorityTier
    source: str
    title: str
    detail: str = ""
    reference: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "emoji": EMOJI[self.tier],
            "label": LABEL[self.tier],
            "source": self.source,
            "title": self.title,
            "detail": self.detail,
            "reference": self.reference,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_date_in_text(text: str) -> datetime | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return datetime(y, mo, d, tzinfo=timezone.utc)
    except ValueError:
        return None


def _gst_heuristic_items(now: datetime) -> list[PriorityItem]:
    """Calendar nudges based on common monthly filing dates (India GST, simplified)."""
    d = now.date()
    day = d.day
    items: list[PriorityItem] = []
    # After typical GSTR-1 date (11th) — verify prior period filed
    if 12 <= day <= 14:
        items.append(
            PriorityItem(
                tier=PriorityTier.emergency,
                source="gst_calendar",
                title="GSTR-1 follow-up",
                detail="Typical monthly GSTR-1 due ~11th — confirm prior period filed if applicable.",
            )
        )
    elif 8 <= day <= 11:
        items.append(
            PriorityItem(
                tier=PriorityTier.urgent,
                source="gst_calendar",
                title="GSTR-1 window",
                detail="Typical GSTR-1 filing window (~by 11th).",
            )
        )
    # GSTR-3B ~20th
    if 21 <= day <= 23:
        items.append(
            PriorityItem(
                tier=PriorityTier.emergency,
                source="gst_calendar",
                title="GSTR-3B follow-up",
                detail="Typical GSTR-3B due ~20th — confirm filing status.",
            )
        )
    elif 17 <= day <= 20:
        items.append(
            PriorityItem(
                tier=PriorityTier.urgent,
                source="gst_calendar",
                title="GSTR-3B window",
                detail="Typical GSTR-3B filing window (~by 20th).",
            )
        )
    if not items:
        items.append(
            PriorityItem(
                tier=PriorityTier.later,
                source="gst_calendar",
                title="GST rhythm",
                detail="No statutory window heuristic active today — keep normal filing discipline.",
            )
        )
    return items


def _meeting_items(now: datetime) -> list[PriorityItem]:
    p = executive_core.load_user_profile()
    km = p.get("key_meetings") or []
    items: list[PriorityItem] = []
    if not isinstance(km, list):
        return items
    today = now.date()
    for m in km:
        if not isinstance(m, str):
            continue
        dt = _parse_iso_date_in_text(m)
        if dt is None:
            items.append(
                PriorityItem(
                    tier=PriorityTier.later,
                    source="meeting",
                    title="Pinned meeting (no date)",
                    detail=m[:200],
                )
            )
            continue
        md = dt.date()
        if md < today:
            items.append(
                PriorityItem(
                    tier=PriorityTier.emergency,
                    source="meeting",
                    title="Missed / past meeting date",
                    detail=m[:240],
                    reference={"date": md.isoformat()},
                )
            )
        elif md == today:
            items.append(
                PriorityItem(
                    tier=PriorityTier.urgent,
                    source="meeting",
                    title="Meeting today",
                    detail=m[:240],
                    reference={"date": md.isoformat()},
                )
            )
        elif md <= today + timedelta(days=2):
            items.append(
                PriorityItem(
                    tier=PriorityTier.urgent,
                    source="meeting",
                    title="Meeting within 48h",
                    detail=m[:240],
                    reference={"date": md.isoformat()},
                )
            )
        else:
            items.append(
                PriorityItem(
                    tier=PriorityTier.later,
                    source="meeting",
                    title="Upcoming meeting",
                    detail=m[:240],
                    reference={"date": md.isoformat()},
                )
            )
    return items


def _inventory_priority_items(inv: dict[str, Any], *, threshold: int) -> list[PriorityItem]:
    items: list[PriorityItem] = []
    if not inv.get("ok"):
        return items
    for row in inv.get("items") or []:
        if not isinstance(row, dict):
            continue
        q = float(row.get("quantity") or 0)
        sku = str(row.get("sku_name") or "?")
        loc = str(row.get("location") or "")
        loc_bit = f" @ {loc}" if loc else ""
        if q <= 0:
            items.append(
                PriorityItem(
                    tier=PriorityTier.emergency,
                    source="inventory",
                    title=f"Stock out: {sku}",
                    detail=f"Quantity {q}{loc_bit}",
                    reference={"sku_name": sku, "quantity": q},
                )
            )
        elif q < max(1.0, threshold / 2):
            items.append(
                PriorityItem(
                    tier=PriorityTier.urgent,
                    source="inventory",
                    title=f"Critically low: {sku}",
                    detail=f"Qty {q} (threshold {threshold}){loc_bit}",
                    reference={"sku_name": sku, "quantity": q},
                )
            )
        else:
            items.append(
                PriorityItem(
                    tier=PriorityTier.later,
                    source="inventory",
                    title=f"Low stock: {sku}",
                    detail=f"Qty {q} (threshold {threshold}){loc_bit}",
                    reference={"sku_name": sku, "quantity": q},
                )
            )
    return items


def _business_depth_priority_items(business_snapshot: dict[str, Any]) -> list[PriorityItem]:
    """
    Phase 4: correlate profit / sales signals with attendance (e.g. delay delivery when short-staffed).
    """
    if not business_snapshot.get("ok"):
        return []
    att = business_snapshot.get("attendance_today") or {}
    profit = business_snapshot.get("profit_month") or {}
    sales = business_snapshot.get("sales_today") or {}

    active = int(att.get("active_staff") or 0)
    absent = int(att.get("absent_estimate") or 0)
    checked = int(att.get("checked_in_today") or 0)

    net_s = (profit.get("net_profit_inr") or "0").strip()
    try:
        net = Decimal(net_s)
    except Exception:
        net = Decimal("0")

    actual_s = (sales.get("actual_inr") or "0").strip()
    try:
        sales_today = Decimal(actual_s)
    except Exception:
        sales_today = Decimal("0")

    items: list[PriorityItem] = []

    if active > 0 and absent >= 2 and net > Decimal("0"):
        items.append(
            PriorityItem(
                tier=PriorityTier.urgent,
                source="business_os",
                title="Profit up but attendance short",
                detail=(
                    f"Month net profit ~₹{net_s} (management KPI); ~{absent} of {active} active staff "
                    f"not checked in today ({checked} checked in). Consider delaying non-critical deliveries or redistributing floor work."
                ),
                reference={
                    "absent_estimate": absent,
                    "active_staff": active,
                    "checked_in_today": checked,
                    "net_profit_inr": net_s,
                },
            )
        )
    elif active > 0 and absent >= 3:
        items.append(
            PriorityItem(
                tier=PriorityTier.urgent,
                source="business_os",
                title="Low attendance today",
                detail=f"~{absent} of {active} active staff not checked in ({checked} checked in). Review coverage before committing to new outbound loads.",
                reference={"absent_estimate": absent, "active_staff": active},
            )
        )

    if sales_today > Decimal("0") and active > 0 and absent >= max(2, active // 2):
        items.append(
            PriorityItem(
                tier=PriorityTier.urgent,
                source="business_os",
                title="Sales activity with thin staffing",
                detail=f"Today's billed revenue ~₹{actual_s} while attendance looks thin (~{absent} absent estimate). Confirm dispatch capacity.",
                reference={"sales_today_inr": actual_s, "absent_estimate": absent},
            )
        )

    return items


def _hitl_priority_items(rows: list[dict[str, Any]]) -> list[PriorityItem]:
    out: list[PriorityItem] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if (r.get("risk_tier") or "").lower() == "high":
            tier = PriorityTier.emergency
        else:
            tier = PriorityTier.urgent
        out.append(
            PriorityItem(
                tier=tier,
                source="hitl",
                title=str(r.get("summary") or r.get("action_type") or "Pending approval"),
                detail=f"Action: {r.get('action_type')}",
                reference={"approval_id": r.get("id")},
            )
        )
    return out


def classify_action_priorities(
    *,
    organization_id: int,
    low_stock_threshold: int = 5,
    _as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Ordered priority queue: Business OS (profit vs attendance), GST heuristics, meetings, inventory, HITL.
    """
    now = _as_of or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    oid = int(organization_id)
    thr = int(low_stock_threshold)

    inv = get_inventory_alerts(organization_id, threshold=thr)
    hitl = list_pending_hitl(organization_id=oid)

    try:
        business_snap = build_business_snapshot(
            oid,
            low_stock_threshold=thr,
            _as_of=now,
        )
    except Exception:
        business_snap = {"ok": False, "error": "business_snapshot_unavailable"}

    bucket: list[PriorityItem] = []
    bucket.extend(_business_depth_priority_items(business_snap))
    bucket.extend(_gst_heuristic_items(now))
    bucket.extend(_meeting_items(now))
    bucket.extend(_inventory_priority_items(inv, threshold=thr))
    bucket.extend(_hitl_priority_items(hitl))

    # Sort: emergency first, then urgent, then later; stable by source
    order = {PriorityTier.emergency: 0, PriorityTier.urgent: 1, PriorityTier.later: 2}
    bucket.sort(key=lambda x: (order[x.tier], x.source, x.title))
    return [b.to_dict() for b in bucket]


def build_unified_snapshot(
    organization_id: int,
    *,
    low_stock_threshold: int = 5,
    _as_of: datetime | None = None,
) -> dict[str, Any]:
    """
    Single JSON payload: analytics summary, inventory alerts, pending HITL, agenda, priorities.
    """
    oid = int(organization_id)
    thr = int(low_stock_threshold)
    analytics = compute_dashboard_summary_sync(
        oid,
        low_stock_threshold=thr,
        _as_of=_as_of,
    )
    inv = list_low_stock_alerts_sync(oid, threshold=thr)
    hitl = list_pending_hitl(organization_id=oid)
    agenda = list_open_agenda_tasks(limit=40)
    priorities = classify_action_priorities(
        organization_id=oid,
        low_stock_threshold=thr,
        _as_of=_as_of,
    )

    try:
        business_snap = build_business_snapshot(
            oid,
            low_stock_threshold=thr,
            _as_of=_as_of or _utc_now(),
        )
    except Exception:
        business_snap = {"ok": False, "error": "business_snapshot_unavailable"}

    counts = {PriorityTier.emergency.value: 0, PriorityTier.urgent.value: 0, PriorityTier.later.value: 0}
    for p in priorities:
        t = p.get("tier")
        if t in counts:
            counts[str(t)] += 1

    return {
        "ok": True,
        "organization_id": oid,
        "as_of_utc": (_as_of or _utc_now()).isoformat(),
        "analytics": analytics,
        "inventory_alerts": inv,
        "pending_hitl": hitl,
        "agenda_open_tasks": agenda,
        "priority_queue": priorities,
        "priority_counts": counts,
        "business_os": business_snap,
    }


def build_command_center_sap_payload_sync(
    user_id: int,
    organization_id: int,
    low_stock_threshold: int = 5,
) -> dict[str, Any]:
    """
    SAP-style unified command center JSON: life + business + AI + merged alert stream.

    Includes **legacy** keys from ``build_unified_snapshot`` (``analytics``, ``inventory_alerts``, …)
    so existing API consumers keep working.
    """
    from core.personal_ai_engine import generate_daily_guidance, merge_director_into_guidance
    from core.personal_director import build_personal_director_bundle_sync
    from core.personal_memory_engine import learn_user_patterns_sync
    from services.personal_engagement_service import compute_daily_score, touch_streak_sync
    from services.personal_jarvis_sync import compute_yesterday_followups_sync
    from services.personal_os_aggregate import build_personal_today_sync

    uid = int(user_id)
    oid = int(organization_id)
    thr = int(low_stock_threshold)
    now = _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if oid > 0:
        unified = build_unified_snapshot(oid, low_stock_threshold=thr, _as_of=now)
    else:
        unified = {
            "ok": True,
            "organization_id": 0,
            "as_of_utc": now.isoformat(),
            "analytics": {"ok": False, "error": "no_organization", "organization_id": 0},
            "inventory_alerts": {"ok": True, "items": [], "count": 0, "threshold": thr},
            "pending_hitl": [],
            "agenda_open_tasks": list_open_agenda_tasks(limit=40),
            "priority_queue": [],
            "priority_counts": {"emergency": 0, "urgent": 0, "later": 0},
            "business_os": {"ok": False, "error": "no_organization"},
        }

    analytics = unified.get("analytics") or {}
    inv = unified.get("inventory_alerts") or {}
    bos = unified.get("business_os") or {}

    payload = build_personal_today_sync(
        user_id=uid,
        organization_id=oid,
        low_stock_threshold=thr,
    )
    payload["authenticated"] = uid > 0
    streak_days = 0
    eng_extra: dict[str, Any] = {}
    if uid > 0:
        st = touch_streak_sync(uid)
        streak_days = int(st.get("streak_days") or 0)
        eng_extra = st.get("extra") or {}
    score_block = (
        compute_daily_score(payload, eng_extra) if uid > 0 else {"daily_score": 0, "daily_score_breakdown": {}}
    )
    payload["streak_days"] = streak_days
    payload["daily_score"] = score_block["daily_score"]
    payload["daily_score_breakdown"] = score_block["daily_score_breakdown"]

    snap: dict[str, Any] = {
        "tasks": payload.get("tasks") or [],
        "reminders": payload.get("reminders") or [],
        "low_stock": payload.get("low_stock") or {},
        "today_sales": payload.get("today_sales") or {},
        "authenticated": uid > 0,
        "user_id": uid,
        "organization_id": oid,
        "daily_score": int(payload.get("daily_score") or 0),
        "streak_days": streak_days,
        "habits_completed_today": int(payload.get("habits_completed_today") or 0),
        "tasks_completed_today": int(payload.get("tasks_completed_today") or 0),
        "jarvis_hour_utc": now.hour,
    }

    director = build_personal_director_bundle_sync(
        payload,
        snap,
        engagement_extra=eng_extra if uid > 0 else None,
    )
    memory = learn_user_patterns_sync(uid, oid) if uid > 0 else {}
    followups = compute_yesterday_followups_sync(uid, payload) if uid > 0 else []
    guidance = generate_daily_guidance(
        snap,
        memory=memory if uid > 0 else None,
        followups=followups or None,
    )
    ge = director.get("guidance_enrichment")
    if isinstance(ge, dict):
        guidance = merge_director_into_guidance(guidance, ge)

    life_score = director.get("life_score") or {}
    life_dashboard: dict[str, Any] = {
        "life_score": life_score,
        "focus_lock": guidance.get("focus_lock") or "",
        "focus_lock_target": guidance.get("focus_lock_target"),
        "top_focus": guidance.get("top_focus") or guidance.get("focus") or "",
        "director_mode": guidance.get("director_mode") or (director.get("life_context") or {}).get("mode"),
        "streak_days": streak_days,
        "daily_score": int(payload.get("daily_score") or 0),
        "tone": guidance.get("tone"),
        "time_mode": guidance.get("time_mode"),
    }

    proactive = list(director.get("proactive_alerts") or [])
    priority_tasks = list(director.get("priority_tasks") or [])
    life_context = dict(director.get("life_context") or {})

    next_best = str(guidance.get("next_best_move") or "").strip()
    if not next_best and isinstance(guidance.get("actionable_suggestions"), list):
        a0 = guidance["actionable_suggestions"][0] if guidance["actionable_suggestions"] else None
        if isinstance(a0, dict) and a0.get("text"):
            next_best = str(a0.get("text") or "").strip()

    ai_decisions: dict[str, Any] = {
        "next_best_move": next_best,
        "priority_tasks": priority_tasks,
        "balance_tip": guidance.get("balance_tip"),
        "memory_based_suggestions": guidance.get("memory_based_suggestions") or [],
        "actionable_suggestions": (guidance.get("actionable_suggestions") or [])[:8],
        "priority_queue_preview": (unified.get("priority_queue") or [])[:6],
    }

    business_summary: dict[str, Any] = {
        "ok": bool(analytics.get("ok")),
        "revenue_inr": analytics.get("revenue_inr") if isinstance(analytics, dict) else {},
        "gst_collected_inr": analytics.get("gst_collected_inr") if isinstance(analytics, dict) else {},
        "top_selling_products": (analytics.get("top_selling_products") or [])[:5]
        if isinstance(analytics, dict)
        else [],
        "profit_month": bos.get("profit_month") if isinstance(bos, dict) else {},
        "sales_today": bos.get("sales_today") if isinstance(bos, dict) else {},
        "attendance_today": bos.get("attendance_today") if isinstance(bos, dict) else {},
    }

    items = inv.get("items") if isinstance(inv.get("items"), list) else []
    inventory_summary: dict[str, Any] = {
        "ok": bool(inv.get("ok", True)),
        "count": int(inv.get("count") or len(items)),
        "threshold": int(inv.get("threshold") or thr),
        "items_preview": [x for x in items[:10] if isinstance(x, dict)],
    }

    alerts: list[str] = []
    for line in guidance.get("alerts") or []:
        if isinstance(line, str) and line.strip():
            alerts.append(line.strip())
    for pa in proactive:
        if not isinstance(pa, dict):
            continue
        pr = int(pa.get("priority") or 99)
        msg = str(pa.get("message") or "").strip()
        if not msg:
            continue
        tag = f"[{pa.get('code') or 'signal'}]"
        if pr <= 2:
            alerts.insert(min(3, len(alerts)), f"{tag} {msg}")
        else:
            alerts.append(f"{tag} {msg}")
    pq = unified.get("priority_queue") or []
    for p in pq[:5]:
        if not isinstance(p, dict):
            continue
        tier = str(p.get("tier") or "")
        if tier == "emergency":
            t = str(p.get("title") or "").strip()
            if t:
                alerts.insert(0, f"[ops:{tier}] {t}")

    seen: set[str] = set()
    deduped: list[str] = []
    for a in alerts:
        k = a[:200]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(a)
    alerts = deduped[:24]

    sap: dict[str, Any] = {
        "schema": "thiramai.command_center.sap.v1",
        "user_id": uid,
        "life_dashboard": life_dashboard,
        "priority_tasks": priority_tasks,
        "proactive_alerts": proactive,
        "life_context": life_context,
        "business_summary": business_summary,
        "inventory_summary": inventory_summary,
        "ai_decisions": ai_decisions,
        "next_best_move": next_best,
        "alerts": alerts,
    }

    out: dict[str, Any] = {**unified, **sap}
    out["as_of_utc"] = unified.get("as_of_utc") or now.isoformat()
    return out


def format_command_center_oneline(snapshot: dict[str, Any]) -> str:
    """Ultra-short line for routine AI responses."""
    if not snapshot.get("ok"):
        return "Command Center: data unavailable."
    c = snapshot.get("priority_counts") or {}
    em, ur, la = int(c.get("emergency", 0)), int(c.get("urgent", 0)), int(c.get("later", 0))
    pq = snapshot.get("priority_queue") or []
    top = ""
    if pq:
        first = pq[0]
        top = f" Top: {first.get('emoji', '')} {first.get('title', '')}."
    hitl_n = len(snapshot.get("pending_hitl") or [])
    low_n = int((snapshot.get("inventory_alerts") or {}).get("count") or 0)
    biz = ""
    bos = snapshot.get("business_os") or {}
    if bos.get("ok"):
        st = bos.get("sales_today") or {}
        att = bos.get("attendance_today") or {}
        pm = bos.get("profit_month") or {}
        biz = (
            f" · Sales today ₹{st.get('actual_inr', '?')} / target ₹{st.get('target_inr', '?')}"
            f" · Staff checked-in {att.get('checked_in_today', '?')}/{att.get('active_staff', '?')}"
            f" · Month net ₹{pm.get('net_profit_inr', '?')}"
        )
    return (
        f"🔴 {em} emergency · 🟠 {ur} urgent · 🟡 {la} later · "
        f"{hitl_n} HITL · {low_n} low-stock SKUs{biz}.{top}"
    )


def user_requests_command_center(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    phrases = (
        "command center",
        "command centre",
        "master dashboard",
        "unified dashboard",
        "priority queue",
        "what is urgent",
        "what's urgent",
        "whats urgent",
        "show priorities",
        "ops overview",
        "operations overview",
    )
    return any(p in t for p in phrases)
