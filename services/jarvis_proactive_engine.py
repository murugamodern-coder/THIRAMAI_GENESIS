"""
Living Jarvis Upgrade 2 / 2.1 — Proactivity + agentic intelligence (scoring, actions, learning).

Orchestrates ``jarvis_proactive_service`` persistence and adds **Insight** objects with
weighted scores, dependency analysis, memory-aware copy, and executable payloads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import JarvisProactiveAlert, UserOrganizationMembership

_log = logging.getLogger("thiramai.jarvis_proactive_engine")


def _priority_rank(p: str) -> int:
    return {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get((p or "").lower(), 4)


def _tool_for_alert_type(typ: str) -> str:
    t = (typ or "").strip().lower()
    if t == "reorder":
        return "create_purchase_order_draft"
    if t == "collection":
        return "draft_business_email"
    if t == "payment":
        return "get_upcoming_emis"
    if t in ("watchlist_move", "breakout", "stock_signal"):
        return "get_stock_price"
    if t == "meeting_soon":
        return "open_calendar"
    return ""


def _base_numeric_scores(alert_type: str, priority_str: str) -> tuple[float, float, float]:
    """Heuristic 0–1 impact, urgency, confidence before memory / feedback."""
    pr = (priority_str or "medium").lower()
    urg = {"urgent": 0.92, "high": 0.78, "medium": 0.55, "low": 0.35}.get(pr, 0.55)
    at = (alert_type or "").lower()
    if at == "reorder":
        return 0.82, urg, 0.72
    if at == "payment":
        return 0.76, max(urg, 0.85), 0.74
    if at == "collection":
        return 0.74, urg, 0.68
    if at == "equity_risk":
        return 0.86, 0.62, 0.88
    if at in ("stock_signal", "watchlist_move"):
        return 0.62, 0.58, 0.70
    if at == "meeting_soon":
        return 0.55, 0.90, 0.80
    if at == "cross_domain":
        return 0.78, 0.70, 0.65
    if at == "weather":
        return 0.42, 0.48, 0.60
    return 0.55, urg, 0.62


def _build_reasoning(*, deps: dict[str, Any], mem_note: str, alert_type: str) -> str:
    parts: list[str] = []
    chain = deps.get("chain")
    if isinstance(chain, list) and chain:
        parts.append(" ".join(str(x) for x in chain if x))
    rec = str(deps.get("recommendation") or "").strip()
    if rec:
        parts.append(rec)
    if mem_note:
        parts.append(mem_note)
    if alert_type == "payment" and not parts:
        parts.append("Upcoming obligation — align with bank / UPI limits before cutoff.")
    out = " ".join(parts).strip()
    return out[:4000] if out else "Prioritized from recent business and personal signals."


@dataclass
class Insight:
    """Proactive item with Upgrade 2.1 scoring and optional executable payload."""

    priority: str
    category: str
    title: str
    message: str
    action: str
    action_tool: str = ""
    priority_score: int = 99
    impact_score: float = 0.5
    urgency_score: float = 0.5
    confidence_score: float = 0.7
    weighted_priority_score: float = 0.0
    reasoning: str = ""
    recommended_action: str = ""
    recommended_action_payload: dict[str, Any] = field(default_factory=dict)
    action_ready_payload: dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "suggest"
    confirm_execute: bool = False
    auto_execute_eligible: bool = False
    dedupe_key: str = ""
    organization_id: int | None = None
    dependency_analysis: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "category": self.category,
            "title": self.title,
            "message": self.message,
            "action": self.action,
            "action_tool": self.action_tool,
            "priority_score": self.priority_score,
            "impact_score": self.impact_score,
            "urgency_score": self.urgency_score,
            "confidence_score": self.confidence_score,
            "weighted_priority_score": self.weighted_priority_score,
            "reasoning": self.reasoning,
            "recommended_action": self.recommended_action,
            "recommended_action_payload": self.recommended_action_payload,
            "action_ready_payload": self.action_ready_payload,
            "execution_mode": self.execution_mode,
            "confirm_execute": self.confirm_execute,
            "auto_execute_eligible": self.auto_execute_eligible,
            "dedupe_key": self.dedupe_key,
            "organization_id": self.organization_id,
            "dependency_analysis": self.dependency_analysis,
        }

    def to_agentic_output(self) -> dict[str, Any]:
        """Canonical API shape (Upgrade 2.1 Step 8)."""
        return {
            "title": self.title,
            "reasoning": self.reasoning,
            "impact": {
                "impact_score": self.impact_score,
                "urgency_score": self.urgency_score,
                "confidence_score": self.confidence_score,
                "priority_score": self.weighted_priority_score,
            },
            "recommended_action": self.recommended_action or self.action,
            "action_ready_payload": self.action_ready_payload,
        }


def _finalize_insight(
    *,
    user_id: int,
    alert_type: str,
    priority: str,
    title: str,
    message: str,
    action: str,
    organization_id: int | None,
    dedupe_key: str,
    payload: dict[str, Any],
) -> Insight:
    from services.jarvis_proactive_action_engine import user_execution_mode_for_user
    from services.jarvis_proactive_intelligence import (
        analyze_dependencies,
        apply_memory_to_scores,
        compute_weighted_priority_score,
        feedback_confidence_multiplier,
        feedback_priority_noise_multiplier,
        fetch_memory_snippets_sync,
    )

    uid = int(user_id)
    at = (alert_type or "general").strip()[:64]
    pr = (priority or "medium").lower()
    if pr not in ("urgent", "high", "medium", "low"):
        pr = "medium"
    pl = payload if isinstance(payload, dict) else {}
    oid = int(organization_id or 0)

    memory = fetch_memory_snippets_sync(user_id=uid)
    deps = analyze_dependencies(alert_type=at, organization_id=oid, payload=pl)
    impact, urgency, confidence = _base_numeric_scores(at, pr)
    impact, urgency, confidence, mem_note = apply_memory_to_scores(
        memory=memory, alert_type=at, impact=impact, urgency=urgency, confidence=confidence
    )

    msg_out = (message or "").strip()
    if at == "payment" and memory.get("cash_stress"):
        if "escalation" not in msg_out.lower():
            msg_out = (
                f"{msg_out} Escalation: memory flags tight cash — fund the EMI early and watch UPI per-day caps."
            )

    fb_conf = feedback_confidence_multiplier(user_id=uid, alert_type=at)
    confidence = max(0.0, min(1.0, confidence * fb_conf))
    noise_m = feedback_priority_noise_multiplier(user_id=uid, alert_type=at)
    if at in ("equity_risk", "stock_signal", "watchlist_move", "breakout"):
        impact = max(0.0, min(1.0, impact * noise_m))

    weighted = compute_weighted_priority_score(impact=impact, urgency=urgency, confidence=confidence)
    weighted *= noise_m

    reasoning = _build_reasoning(deps=deps, mem_note=mem_note, alert_type=at)
    tool = _tool_for_alert_type(at)
    mode = user_execution_mode_for_user(uid)

    action_ready: dict[str, Any] = {}
    rec_payload: dict[str, Any] = {"handler": tool, "alert_type": at, "dedupe_key": dedupe_key}
    if at == "reorder" and oid > 0:
        from services.jarvis_proactive_action_engine import build_reorder_po_draft_payload_sync

        sku = str(pl.get("sku") or pl.get("sku_name") or "").strip()
        action_ready = build_reorder_po_draft_payload_sync(
            organization_id=oid,
            sku=sku,
            user_id=uid,
            quantity_hint=pl.get("quantity"),
        )
        rec_payload = {**rec_payload, **{k: v for k, v in action_ready.items() if k != "notes"}}
    elif at == "payment":
        rec_payload["loan_id"] = pl.get("loan_id")
        action_ready = {
            "ok": True,
            "handler": "schedule_emi_reminder",
            "loan_id": pl.get("loan_id"),
            "user_id": uid,
            "urgency": "high" if memory.get("cash_stress") else "normal",
        }

    exec_mode = mode
    confirm_ex = bool(action_ready.get("ok")) and exec_mode == "confirm" and at in ("reorder", "payment")
    auto_elig = bool(action_ready.get("ok")) and exec_mode == "auto" and at == "reorder"

    return Insight(
        priority=pr,
        category=at,
        title=(title or msg_out[:120]).strip()[:200],
        message=msg_out[:8000],
        action=(action or "").strip()[:4000],
        action_tool=tool,
        priority_score=_priority_rank(pr),
        impact_score=round(impact, 4),
        urgency_score=round(urgency, 4),
        confidence_score=round(confidence, 4),
        weighted_priority_score=round(weighted, 3),
        reasoning=reasoning,
        recommended_action=(deps.get("recommendation") or action or "").strip()[:2000],
        recommended_action_payload=rec_payload,
        action_ready_payload=action_ready,
        execution_mode=exec_mode,
        confirm_execute=confirm_ex,
        auto_execute_eligible=auto_elig,
        dedupe_key=(dedupe_key or "")[:256],
        organization_id=organization_id,
        dependency_analysis=deps,
    )


def _dict_to_insight(a: dict[str, Any]) -> Insight | None:
    if not isinstance(a, dict):
        return None
    pr = str(a.get("priority") or "medium").lower()
    typ = str(a.get("type") or a.get("alert_type") or "general").strip()
    msg = str(a.get("message") or "").strip()
    if not msg:
        return None
    title = msg[:72] + ("…" if len(msg) > 72 else "")
    act = str(a.get("action") or a.get("action_text") or "Open Today / Command Center")
    oid = a.get("organization_id")
    org_id = int(oid) if oid is not None and str(oid).isdigit() else (int(oid) if isinstance(oid, int) else None)
    if org_id is not None and org_id <= 0:
        org_id = None
    dk = str(a.get("dedupe_key") or "")
    pl = a.get("payload") if isinstance(a.get("payload"), dict) else {}
    uid = int(a.get("_user_id") or 0)
    if uid <= 0:
        return Insight(
            priority=pr if pr in ("urgent", "high", "medium", "low") else "medium",
            category=typ,
            title=title,
            message=msg[:2000],
            action=act,
            action_tool=_tool_for_alert_type(typ),
            priority_score=_priority_rank(pr),
        )
    return _finalize_insight(
        user_id=uid,
        alert_type=typ,
        priority=pr,
        title=title,
        message=msg,
        action=act,
        organization_id=org_id,
        dedupe_key=dk,
        payload=pl,
    )


def _org_ids_for_user(user_id: int) -> list[int]:
    uid = int(user_id)
    if uid <= 0:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    with factory() as session:
        return [
            int(x)
            for x in session.scalars(
                select(UserOrganizationMembership.organization_id).where(
                    UserOrganizationMembership.user_id == uid,
                    UserOrganizationMembership.is_active.is_(True),
                )
            ).all()
        ]


def _weather_tn_insight(user_id: int) -> Insight | None:
    try:
        import httpx

        url = (
            "https://api.open-meteo.com/v1/forecast?latitude=13.08&longitude=80.27"
            "&daily=precipitation_probability_max&timezone=Asia%2FKolkata&forecast_days=1"
        )
        r = httpx.get(url, timeout=10.0)
        r.raise_for_status()
        data = r.json()
        daily = data.get("daily") if isinstance(data.get("daily"), dict) else {}
        arr = daily.get("precipitation_probability_max")
        if not isinstance(arr, list) or not arr:
            return None
        pct = float(arr[0])
        if pct < 70.0:
            return None
        return _finalize_insight(
            user_id=int(user_id),
            alert_type="weather",
            priority="medium",
            title="Rain expected — protect materials",
            message=f"~{pct:.0f}% max rain probability today (Chennai reference). Cover raw materials if exposed.",
            action="Send alert to workers / reschedule outdoor work",
            organization_id=None,
            dedupe_key=f"weather:tn:{pct:.0f}",
            payload={"region": "chennai_ref", "precip_prob_max": pct},
        )
    except Exception as exc:
        _log.debug("weather insight skipped: %s", exc)
        return None


def _cross_domain_equity_insight(user_id: int) -> Insight | None:
    uid = int(user_id)
    if uid <= 0:
        return None
    try:
        from services.portfolio_service import daily_equity_pnl_inr_sync

        pnl = daily_equity_pnl_inr_sync(uid)
        if pnl >= Decimal("-2000"):
            return None
        loss = abs(float(pnl))
        approx_days = max(1, int(loss / 1500))
        msg = (
            f"Today's paper equity P&L is about ₹{loss:,.0f}. That can be ~{approx_days} day(s) of "
            "typical small-business opex if unplanned — consider pausing new trades and collecting receivables."
        )
        return _finalize_insight(
            user_id=uid,
            alert_type="cross_domain",
            priority="high",
            title="Stock loss vs business cash",
            message=msg,
            action="Review risk limits and invoices",
            organization_id=None,
            dedupe_key=f"cross_eq:{uid}",
            payload={"daily_realized_pnl_inr": str(pnl)},
        )
    except Exception as exc:
        _log.debug("cross_domain equity insight skipped: %s", exc)
        return None


def _row_dict_to_insight(user_id: int, row: dict[str, Any]) -> Insight | None:
    if not isinstance(row, dict):
        return None
    msg = str(row.get("message") or "").strip()
    if not msg:
        return None
    title = msg[:72] + ("…" if len(msg) > 72 else "")
    return _finalize_insight(
        user_id=int(user_id),
        alert_type=str(row.get("alert_type") or "general"),
        priority=str(row.get("priority") or "medium"),
        title=title,
        message=msg,
        action=str(row.get("action_text") or ""),
        organization_id=row.get("organization_id"),
        dedupe_key=str(row.get("dedupe_key") or ""),
        payload=row.get("payload") if isinstance(row.get("payload"), dict) else {},
    )


class JarvisProactiveEngine:
    """Upgrade 2 / 2.1 entrypoint: prioritized insights, batch jobs, optional execution."""

    def run_morning_intelligence(self, user_id: int) -> list[Insight]:
        from services.jarvis_proactive_service import generate_morning_intelligence_sync

        uid = int(user_id)
        oids = _org_ids_for_user(uid)
        if not oids:
            return []
        out = generate_morning_intelligence_sync(user_id=uid, organization_ids=oids[:5])
        raw = out.get("alerts") if isinstance(out.get("alerts"), list) else []
        insights: list[Insight] = []
        for a in raw:
            if not isinstance(a, dict):
                continue
            a2 = {**a, "_user_id": uid}
            ins = _dict_to_insight(a2)
            if ins:
                insights.append(ins)
        wi = _weather_tn_insight(uid)
        if wi:
            insights.append(wi)
        ci = _cross_domain_equity_insight(uid)
        if ci:
            insights.append(ci)
        insights.sort(key=lambda x: (-float(x.weighted_priority_score or 0), x.priority_score, x.title))
        return insights[:5]

    def run_realtime_checks(self, user_id: int) -> list[Insight]:
        from services.jarvis_proactive_service import run_realtime_intelligence_sync

        uid = int(user_id)
        oids = _org_ids_for_user(uid)
        if not oids:
            return []
        out = run_realtime_intelligence_sync(user_id=uid, organization_ids=oids[:5])
        raw = out.get("alerts") if isinstance(out.get("alerts"), list) else []
        insights: list[Insight] = []
        for a in raw:
            if not isinstance(a, dict):
                continue
            a2 = {**a, "_user_id": uid, "type": a.get("type") or a.get("alert_type") or "general"}
            ins = _dict_to_insight(a2)
            if ins:
                insights.append(ins)
        insights.sort(key=lambda x: (-float(x.weighted_priority_score or 0), x.priority_score))
        return insights[:5]

    @staticmethod
    def build_intelligent_insights_from_recent(user_id: int, *, limit: int = 12) -> list[Insight]:
        """Read persisted alerts and re-score with memory, dependencies, learning, and actions."""
        from services.jarvis_proactive_service import list_recent_proactive_full_sync

        uid = int(user_id)
        if uid <= 0:
            return []
        rows = list_recent_proactive_full_sync(user_id=uid, limit=limit, days=7)
        insights: list[Insight] = []
        for row in rows:
            ins = _row_dict_to_insight(uid, row)
            if ins:
                insights.append(ins)
        insights.sort(key=lambda x: (-float(x.weighted_priority_score or 0), x.priority_score))
        return insights

    @staticmethod
    def run_morning_intelligence_all_users() -> dict[str, Any]:
        from services.jarvis_proactive_service import run_morning_job_all_users_sync

        return run_morning_job_all_users_sync()

    @staticmethod
    def run_realtime_checks_all_users() -> dict[str, Any]:
        from services.jarvis_proactive_service import run_realtime_job_all_users_sync

        return run_realtime_job_all_users_sync()


def execute_proactive_insight_action_sync(*, user_id: int, dedupe_key: str) -> dict[str, Any]:
    """
    Explicit execution entry (confirm/auto modes). Resolves alert by dedupe_key and runs safe handlers.
    """
    uid = int(user_id)
    dk = (dedupe_key or "").strip()[:256]
    if uid <= 0 or not dk:
        return {"ok": False, "error": "user_id and dedupe_key required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    with factory() as session:
        row = session.execute(
            select(JarvisProactiveAlert).where(
                JarvisProactiveAlert.user_id == uid,
                JarvisProactiveAlert.dedupe_key == dk,
            ).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return {"ok": False, "error": "alert not found"}
        rdict = {
            "alert_type": row.alert_type,
            "priority": row.priority,
            "message": row.message,
            "action_text": row.action_text,
            "payload": row.payload if isinstance(row.payload, dict) else {},
            "dedupe_key": row.dedupe_key,
            "organization_id": int(row.organization_id) if row.organization_id else None,
        }
    ins = _row_dict_to_insight(uid, rdict)
    if ins is None:
        return {"ok": False, "error": "could not build insight"}
    from services.jarvis_proactive_action_engine import try_execute_create_po_draft, user_execution_mode_for_user

    mode = user_execution_mode_for_user(uid)
    if mode == "suggest":
        return {"ok": True, "skipped": "execution_mode_suggest", "insight": ins.to_agentic_output()}
    if ins.category == "reorder" and ins.action_ready_payload.get("handler") == "create_purchase_order_draft":
        ex = try_execute_create_po_draft(user_id=uid, payload=ins.action_ready_payload)
        if ex is not None:
            return {"ok": True, "executed": True, "detail": ex, "insight": ins.to_agentic_output()}
        return {"ok": True, "executed": False, "insight": ins.to_agentic_output(), "note": "auto preconditions not met"}
    return {"ok": True, "executed": False, "insight": ins.to_agentic_output(), "note": "no auto handler for this type"}
