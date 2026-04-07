"""
Phase 4 — autonomous business-event → AI decision → persist / execute (reuse Phase 3).

Schedulers call ``run_automation_scan_for_all_orgs`` (see ``workers.alert_worker``).
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from core.database import get_session_factory, session_scope
from core.db.models import AiDecision
from core.decision_schema import AIDecision, decision_is_safe, parse_and_validate_decision
from core.decision_rbac import can_execute_decision
from services import action_executor
from services import approval_service as ai_decision_store
from services import audit_log as system_audit
from services import inventory_phase2_service as inv2
from services.context_engine import build_business_context_snapshot
from services.decision_brain import run_decision_engine_sync

_log = logging.getLogger("thiramai.decision_trigger")

# Automation runs as a synthetic **owner**-equivalent role for RBAC (no interactive user).
AUTOMATION_ROLE = "owner"


def _truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int((os.getenv(name) or str(default)).strip()))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _automation_max_per_hour() -> int:
    return max(1, _int_env("THIRAMAI_AUTOMATION_MAX_DECISIONS_PER_ORG_PER_HOUR", 24))


def _dedupe_hours() -> int:
    return max(1, _int_env("THIRAMAI_AUTOMATION_DEDUPE_HOURS", 24))


def _low_stock_max_per_run() -> int:
    return max(1, _int_env("THIRAMAI_AUTOMATION_LOW_STOCK_MAX_PER_RUN", 3))


def _waste_pct_threshold() -> float:
    return max(0.0, _float_env("THIRAMAI_AUTOMATION_WASTE_PCT_THRESHOLD", 25.0))


def _auto_approve_low_stock() -> bool:
    return _truthy("THIRAMAI_AUTOMATION_AUTO_APPROVE_LOW_STOCK", "0")


def _auto_approve_reminders() -> bool:
    return _truthy("THIRAMAI_AUTOMATION_AUTO_APPROVE_REMINDERS", "1")


def _count_automation_decisions_last_hour(organization_id: int) -> int:
    oid = int(organization_id)
    factory = get_session_factory()
    if factory is None:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    with factory() as session:
        n = session.scalar(
            select(func.count())
            .select_from(AiDecision)
            .where(
                AiDecision.organization_id == oid,
                AiDecision.correlation_id.is_not(None),
                AiDecision.correlation_id.like("automation:%"),
                AiDecision.created_at >= cutoff,
            )
        )
        return int(n or 0)


def _correlation_exists_in_window(correlation_id: str, hours: int) -> bool:
    factory = get_session_factory()
    if factory is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with factory() as session:
        row = session.scalar(
            select(AiDecision.id).where(
                AiDecision.correlation_id == correlation_id[:128],
                AiDecision.created_at >= cutoff,
            ).limit(1)
        )
        return row is not None


def _decision_from_brain_bundle(bundle: dict[str, Any]) -> AIDecision | None:
    dec_dict = bundle.get("decision")
    if not dec_dict or not bundle.get("ok"):
        return None
    try:
        d, err = parse_and_validate_decision(dec_dict)
        if err or d is None:
            return None
        return d
    except Exception:
        return None


def _fallback_reorder_from_alert(alert: dict[str, Any]) -> AIDecision:
    sku = str(alert.get("sku_name") or "").strip()
    q = float(alert.get("quantity") or 0)
    rp = alert.get("reorder_point")
    try:
        rp_f = float(rp) if rp is not None else 0.0
    except (TypeError, ValueError):
        rp_f = 0.0
    suggested = max(1.0, (rp_f - q + 1.0) if rp_f > q else 10.0)
    suggested = min(suggested, 1_000_000.0)
    return AIDecision(
        action="reorder_stock",
        entity="inventory_item",
        data={
            "sku_name": sku,
            "quantity": suggested,
            "location": str(alert.get("location") or ""),
        },
        priority="high",
        requires_approval=not _auto_approve_low_stock(),
        rationale="Automated low-stock reorder proposal (deterministic fallback).",
    )


def persist_and_maybe_execute(
    *,
    organization_id: int,
    decision: AIDecision,
    correlation_id: str,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Same contract as ``POST /chat/decision``: RBAC + safety → pending or executed row in ``ai_decisions``.
    """
    oid = int(organization_id)
    cid = (correlation_id or "")[:128]

    rbac_ok, rbac_err = can_execute_decision(role_name=AUTOMATION_ROLE, decision=decision)
    if not rbac_ok:
        system_audit.record_system_audit(
            action="automation_decision",
            outcome="failure",
            organization_id=oid,
            user_id=user_id,
            resource_type="ai_decision",
            metadata={
                "channel": "decision_trigger.persist",
                "correlation_id": cid,
                "reason": "rbac",
                "detail": rbac_err,
            },
        )
        return {"ok": False, "error": rbac_err or "rbac denied"}

    safe_ok, safe_err = decision_is_safe(decision)
    if not safe_ok:
        system_audit.record_system_audit(
            action="automation_decision",
            outcome="failure",
            organization_id=oid,
            user_id=user_id,
            resource_type="ai_decision",
            metadata={
                "channel": "decision_trigger.persist",
                "correlation_id": cid,
                "reason": "safety",
                "detail": safe_err,
            },
        )
        return {"ok": False, "error": safe_err or "unsafe"}

    if decision.requires_approval:
        ins = ai_decision_store.insert_ai_decision(
            organization_id=oid,
            user_id=user_id,
            decision=decision,
            status="pending",
            correlation_id=cid,
        )
        if not ins.get("ok"):
            return {"ok": False, "error": ins.get("error") or "persist failed"}
        system_audit.record_system_audit(
            action="automation_decision",
            outcome="pending",
            organization_id=oid,
            user_id=user_id,
            resource_type="ai_decision",
            metadata={
                "channel": "decision_trigger.automation",
                "correlation_id": cid,
                "decision_id": ins.get("id"),
                "action": decision.action,
                "requires_approval": True,
            },
        )
        return {"ok": True, "phase": "pending", "decision_id": ins.get("id"), "execution": None}

    ex = action_executor.execute_decision(
        organization_id=oid,
        decision=decision,
        user_id=user_id,
    )
    ins = ai_decision_store.insert_ai_decision(
        organization_id=oid,
        user_id=user_id,
        decision=decision,
        status="executed" if ex.get("ok") else "failed",
        correlation_id=cid,
        execution_result=ex.get("result") if ex.get("ok") else None,
        error_message=None if ex.get("ok") else str(ex.get("error") or "execution failed"),
    )
    if not ins.get("ok"):
        return {"ok": False, "error": ins.get("error") or "persist failed"}
    system_audit.record_system_audit(
        action="automation_decision",
        outcome="success" if ex.get("ok") else "failure",
        organization_id=oid,
        user_id=user_id,
        resource_type="ai_decision",
        metadata={
            "channel": "decision_trigger.automation",
            "correlation_id": cid,
            "decision_id": ins.get("id"),
            "action": decision.action,
            "executed": bool(ex.get("ok")),
        },
    )
    return {"ok": bool(ex.get("ok")), "phase": "executed" if ex.get("ok") else "failed", "execution": ex, "decision_id": ins.get("id")}


def process_low_stock_automation(organization_id: int) -> dict[str, Any]:
    """Inventory alerts → ``reorder_stock`` (Groq JSON if possible, else deterministic)."""
    oid = int(organization_id)
    out: dict[str, Any] = {"ok": True, "triggered": 0, "skipped": 0}
    low = inv2.list_low_stock_alerts_sync(organization_id=oid)
    if not low.get("ok"):
        return {"ok": False, "error": low.get("error")}

    alerts = list(low.get("alerts") or [])[: _low_stock_max_per_run()]
    today = date.today().isoformat()
    for a in alerts:
        if _count_automation_decisions_last_hour(oid) >= _automation_max_per_hour():
            out["rate_limited"] = True
            break
        iid = int(a.get("id") or 0)
        corr = f"automation:low_stock:{oid}:{iid}:{today}"
        if _correlation_exists_in_window(corr, _dedupe_hours()):
            out["skipped"] += 1
            continue

        msg = (
            f"[AUTOMATION] Low stock signal. Inventory item id={iid}, sku={a.get('sku_name')!r}, "
            f"qty={a.get('quantity')}, reorder_point={a.get('reorder_point')}. "
            f"Emit reorder_stock with safe quantity and requires_approval as appropriate."
        )
        bundle = run_decision_engine_sync(
            msg,
            oid,
            actor_role_name=AUTOMATION_ROLE,
            user_id=None,
            correlation_id=corr,
        )
        decision = _decision_from_brain_bundle(bundle)
        if decision is None or decision.action != "reorder_stock":
            decision = _fallback_reorder_from_alert(a)
        else:
            s_ok, _ = decision_is_safe(decision)
            if not s_ok:
                decision = _fallback_reorder_from_alert(a)

        pr = persist_and_maybe_execute(
            organization_id=oid,
            decision=decision,
            correlation_id=corr,
            user_id=None,
        )
        if pr.get("ok"):
            out["triggered"] += 1
        else:
            _log.warning("automation low_stock persist failed org=%s err=%s", oid, pr.get("error"))
    return out


def process_overdue_invoice_automation(organization_id: int) -> dict[str, Any]:
    """Overdue unpaid invoices → ``send_payment_reminder``."""
    oid = int(organization_id)
    ctx = build_business_context_snapshot(oid)
    fin = ctx.get("financial_summary") if isinstance(ctx.get("financial_summary"), dict) else {}
    overdue_ids = fin.get("overdue_invoice_ids") if isinstance(fin.get("overdue_invoice_ids"), list) else []
    if not overdue_ids:
        return {"ok": True, "triggered": 0, "skipped": 0}

    inv_id = int(overdue_ids[0])
    today = date.today().isoformat()
    corr = f"automation:payment_reminder:{oid}:{inv_id}:{today}"
    if _correlation_exists_in_window(corr, _dedupe_hours()):
        return {"ok": True, "triggered": 0, "skipped": 1}
    if _count_automation_decisions_last_hour(oid) >= _automation_max_per_hour():
        return {"ok": True, "triggered": 0, "skipped": 1, "rate_limited": True}

    msg = (
        f"[AUTOMATION] Overdue invoice id={inv_id}. "
        f"Emit send_payment_reminder with invoice_id and a short message for the dashboard."
    )
    bundle = run_decision_engine_sync(
        msg,
        oid,
        actor_role_name=AUTOMATION_ROLE,
        user_id=None,
        correlation_id=corr,
    )
    decision = _decision_from_brain_bundle(bundle)
    if decision is None or decision.action not in ("send_payment_reminder", "send_alert"):
        decision = AIDecision(
            action="send_payment_reminder",
            entity="invoice",
            data={
                "invoice_id": inv_id,
                "message": f"Invoice #{inv_id} is overdue — please review payment status.",
            },
            priority="high",
            requires_approval=not _auto_approve_reminders(),
            rationale="Automated overdue payment reminder",
        )
    if decision.action == "send_alert":
        decision = AIDecision(
            action="send_payment_reminder",
            entity="invoice",
            data={
                "invoice_id": inv_id,
                "message": str(decision.data.get("message") or f"Invoice #{inv_id} needs attention.")[:2000],
            },
            priority=decision.priority,
            requires_approval=decision.requires_approval,
            rationale=decision.rationale or "Automated reminder",
        )

    pr = persist_and_maybe_execute(
        organization_id=oid,
        decision=decision,
        correlation_id=corr,
        user_id=None,
    )
    return {
        "ok": bool(pr.get("ok")),
        "triggered": 1 if pr.get("ok") else 0,
        "error": pr.get("error"),
    }


def process_production_signals_automation(organization_id: int) -> dict[str, Any]:
    """High waste % or machine downtime → ``send_alert`` (or ``create_task`` if model proposes one)."""
    oid = int(organization_id)
    ctx = build_business_context_snapshot(oid)
    ps = ctx.get("production_status") if isinstance(ctx.get("production_status"), dict) else {}
    waste = ps.get("waste_percent_estimate")
    machines = ps.get("machines") if isinstance(ps.get("machines"), dict) else {}
    down = int(machines.get("down_or_maintenance_count") or 0)

    waste_f: float | None = None
    if isinstance(waste, (int, float)):
        waste_f = float(waste)

    if waste_f is None and down <= 0:
        return {"ok": True, "triggered": 0, "skipped": 0}

    if waste_f is not None and waste_f < _waste_pct_threshold() and down <= 0:
        return {"ok": True, "triggered": 0, "skipped": 0}

    today = date.today().isoformat()
    corr = f"automation:production:{oid}:{today}"
    if _correlation_exists_in_window(corr, _dedupe_hours()):
        return {"ok": True, "triggered": 0, "skipped": 1}
    if _count_automation_decisions_last_hour(oid) >= _automation_max_per_hour():
        return {"ok": True, "triggered": 0, "skipped": 1, "rate_limited": True}

    msg = (
        f"[AUTOMATION] Production signal: waste_percent_estimate={waste_f}, "
        f"machines_down_or_maintenance={down}. "
        f"Prefer send_alert or create_task with asset_id if known from context."
    )
    bundle = run_decision_engine_sync(
        msg,
        oid,
        actor_role_name=AUTOMATION_ROLE,
        user_id=None,
        correlation_id=corr,
    )
    decision = _decision_from_brain_bundle(bundle)
    if decision is None or decision.action not in ("send_alert", "create_task", "noop"):
        parts = []
        if waste_f is not None and waste_f >= _waste_pct_threshold():
            parts.append(f"Estimated waste high (~{waste_f}%).")
        if down > 0:
            parts.append(f"{down} machine(s) down or in maintenance.")
        decision = AIDecision(
            action="send_alert",
            entity="production",
            data={"message": " ".join(parts) or "Production anomaly detected."},
            priority="high",
            requires_approval=True,
            rationale="Automated production anomaly alert",
        )

    if decision.action == "noop":
        return {"ok": True, "triggered": 0, "skipped": 1}

    pr = persist_and_maybe_execute(
        organization_id=oid,
        decision=decision,
        correlation_id=corr,
        user_id=None,
    )
    return {
        "ok": bool(pr.get("ok")),
        "triggered": 1 if pr.get("ok") else 0,
        "error": pr.get("error"),
    }


def process_organization_automation(organization_id: int) -> dict[str, Any]:
    """Run inventory → billing → production checks for one tenant."""
    oid = int(organization_id)
    inv = process_low_stock_automation(oid)
    bill = process_overdue_invoice_automation(oid)
    prod = process_production_signals_automation(oid)
    return {
        "ok": True,
        "organization_id": oid,
        "inventory": inv,
        "billing": bill,
        "production": prod,
    }


def run_automation_scan_for_all_orgs() -> None:
    """Entry point for APScheduler (loads active orgs)."""
    try:
        from services.worker_heartbeat import touch_heartbeat

        touch_heartbeat("automation_worker")
    except Exception:
        pass

    factory = get_session_factory()
    if factory is None:
        _log.warning("decision_trigger: DATABASE_URL not set; automation scan skipped")
        return

    try:
        from workers.alert_system import active_organization_ids
    except Exception as exc:
        _log.warning("decision_trigger: cannot import alert_system: %s", exc)
        return

    try:
        with session_scope() as session:
            org_ids = active_organization_ids(session)
    except Exception as exc:
        _log.exception("decision_trigger: org list failed: %s", exc)
        return

    for oid in org_ids:
        try:
            process_organization_automation(oid)
        except Exception as exc:
            _log.exception("decision_trigger: org %s failed: %s", oid, exc)
