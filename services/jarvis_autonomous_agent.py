"""
Upgrade 2.2 — Autonomous agent: goal-driven planning, safe execution, learning, daily plans.

The **continuous** loop is implemented as ``run_agent_cycle_sync`` (one tick) and optional
``run_continuous_agent`` for dedicated worker processes — never block the API thread indefinitely.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import func, select

from core.database import get_session_factory
from core.db.models import JarvisAgentActionLog, JarvisDailyAgentPlan, JarvisFact

_log = logging.getLogger("thiramai.jarvis_autonomous_agent")

# Step 7 — never auto-execute high-risk families (even if mode is "auto").
FORBIDDEN_AUTONOMOUS_KINDS: frozenset[str] = frozenset(
    {
        "payment_execute",
        "wire_transfer",
        "stock_trade",
        "equity_trade",
        "place_order",
        "execute_payment",
    }
)

ALLOWED_AUTONOMOUS_KINDS: frozenset[str] = frozenset(
    {
        "create_purchase_order_draft",
        "schedule_emi_reminder",
        "reminder_log",
        "noop_log",
        "goal_subtask",
    }
)

_INSIGHT_CACHE: dict[tuple[int, str], tuple[float, list[dict[str, Any]]]] = {}
_LAST_CYCLE_TS: dict[int, float] = {}
_DEDUPE_DAY: dict[int, str] = {}
_DEDUPE_FP: dict[int, set[str]] = {}


def is_safe_autonomous_action(action_kind: str) -> bool:
    k = (action_kind or "").strip().lower()
    if k in FORBIDDEN_AUTONOMOUS_KINDS:
        return False
    if k in ALLOWED_AUTONOMOUS_KINDS:
        return True
    return k.startswith("draft_") or k.endswith("_reminder")


def _cache_ttl_seconds() -> float:
    try:
        return max(60.0, float((os.getenv("THIRAMAI_AGENT_INSIGHT_CACHE_SEC") or "300").strip()))
    except ValueError:
        return 300.0


def _cycle_interval_seconds() -> float:
    try:
        mins = max(1.0, float((os.getenv("THIRAMAI_AGENT_CYCLE_MINUTES") or "30").strip()))
    except ValueError:
        mins = 30.0
    return mins * 60.0


def _fingerprint(step: dict[str, Any]) -> str:
    raw = json.dumps(step, sort_keys=True, default=str)[:4000]
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_cached_proactive_insights_sync(*, user_id: int) -> list[dict[str, Any]]:
    """Step 10 — short TTL cache of agentic insight dicts."""
    uid = int(user_id)
    if uid <= 0:
        return []
    key = (uid, "agentic")
    now = time.monotonic()
    ttl = _cache_ttl_seconds()
    hit = _INSIGHT_CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return list(hit[1])
    from services.jarvis_proactive_engine import JarvisProactiveEngine

    rows = JarvisProactiveEngine.build_intelligent_insights_from_recent(uid, limit=10)
    serialized = [r.to_agentic_output() for r in rows]
    _INSIGHT_CACHE[key] = (now, serialized)
    return list(serialized)


def simulate_reorder_outcome_sync(
    *,
    user_id: int,
    organization_id: int,
    sku: str,
    quantity_hint: Any = None,
) -> dict[str, Any]:
    """
    Step 6 — lightweight simulation before a reorder action (supplier, budget sketch, demand hint).
    """
    from services.jarvis_proactive_intelligence import analyze_dependencies

    oid = int(organization_id)
    sku_s = (sku or "").strip()
    pl = {"sku": sku_s, "quantity": quantity_hint}
    deps = analyze_dependencies(alert_type="reorder", organization_id=oid, payload=pl)
    sim: dict[str, Any] = {
        "ok": True,
        "sku": sku_s,
        "dependency_chain": deps.get("chain"),
        "budget_note": deps.get("budget_note"),
        "supplier": deps.get("supplier"),
        "recommendation": deps.get("recommendation"),
        "risk_flags": [],
    }
    if not deps.get("supplier"):
        sim["risk_flags"].append("no_supplier")
    if not sku_s:
        sim["ok"] = False
        sim["risk_flags"].append("missing_sku")
    return sim


def log_agent_action_sync(
    *,
    user_id: int,
    action_kind: str,
    outcome: str,
    payload: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> dict[str, Any]:
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    oc = (outcome or "").strip().lower()[:32]
    if oc not in ("success", "partial", "failed", "skipped"):
        oc = "skipped"
    pl = payload if isinstance(payload, dict) else {}
    with factory() as session:
        with session.begin():
            session.add(
                JarvisAgentActionLog(
                    user_id=uid,
                    action_kind=(action_kind or "unknown")[:64],
                    payload=pl,
                    outcome=oc,
                    detail=detail if isinstance(detail, dict) else None,
                    retry_count=max(0, int(retry_count)),
                )
            )
    return {"ok": True}


def _merge_stats(existing: dict[str, Any], action_kind: str, outcome: str) -> dict[str, Any]:
    st = dict(existing)
    ak = (action_kind or "unknown")[:64]
    bucket = st.setdefault(ak, {"success": 0, "partial": 0, "failed": 0, "n": 0})
    bucket["n"] = int(bucket.get("n") or 0) + 1
    if outcome == "success":
        bucket["success"] = int(bucket.get("success") or 0) + 1
    elif outcome == "partial":
        bucket["partial"] = int(bucket.get("partial") or 0) + 1
    else:
        bucket["failed"] = int(bucket.get("failed") or 0) + 1
    return st


def update_learning_stats_sync(*, user_id: int, action_kind: str, outcome: str) -> None:
    """Step 4 — persist rolling success rates in ``JarvisFact`` (JSON string)."""
    uid = int(user_id)
    if uid <= 0:
        return
    factory = get_session_factory()
    if factory is None:
        return
    try:
        with factory() as session:
            with session.begin():
                row = session.execute(
                    select(JarvisFact).where(
                        JarvisFact.user_id == uid,
                        JarvisFact.fact_type == "agent_learning",
                        JarvisFact.key == "action_outcome_stats",
                    ).limit(1)
                ).scalar_one_or_none()
                prev: dict[str, Any] = {}
                if row and row.value:
                    try:
                        prev = json.loads(row.value)
                    except Exception:
                        prev = {}
                merged = _merge_stats(prev if isinstance(prev, dict) else {}, action_kind, outcome)
                blob = json.dumps(merged)[:12000]
                now = datetime.now(timezone.utc)
                if row:
                    r2 = session.get(JarvisFact, row.id)
                    if r2:
                        r2.value = blob
                        r2.last_verified = now
                else:
                    session.add(
                        JarvisFact(
                            user_id=uid,
                            fact_type="agent_learning",
                            key="action_outcome_stats",
                            value=blob,
                            confidence=Decimal("0.75"),
                            source="autonomous_agent",
                            last_verified=now,
                        )
                    )
    except Exception as exc:
        _log.debug("update_learning_stats_sync: %s", exc)


def dynamic_confidence_for_action_sync(*, user_id: int, action_kind: str) -> float:
    """Scale 0–1 confidence from historical outcomes (Step 4)."""
    uid = int(user_id)
    factory = get_session_factory()
    if factory is None:
        return 0.65
    try:
        with factory() as session:
            row = session.execute(
                select(JarvisFact).where(
                    JarvisFact.user_id == uid,
                    JarvisFact.fact_type == "agent_learning",
                    JarvisFact.key == "action_outcome_stats",
                ).limit(1)
            ).scalar_one_or_none()
        if not row or not row.value:
            return 0.65
        data = json.loads(row.value)
        b = data.get((action_kind or "")[:64]) if isinstance(data, dict) else None
        if not isinstance(b, dict):
            return 0.65
        n = int(b.get("n") or 0)
        if n <= 0:
            return 0.65
        ok = int(b.get("success") or 0) + 0.5 * int(b.get("partial") or 0)
        return max(0.2, min(0.98, ok / float(n)))
    except Exception:
        return 0.65


def maybe_upgrade_execution_mode_fact_sync(*, user_id: int) -> dict[str, Any]:
    """
    Step 5 — if user consistently **acts** on proactive feedback, suggest ``auto`` via fact
    (opt-in; respects human review until they keep ``suggest``).
    """
    from services.jarvis_proactive_intelligence import count_recent_outcomes_sync

    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "invalid user"}
    cur: JarvisFact | None = None
    factory = get_session_factory()
    if factory is None:
        return {"ok": True, "upgraded": False, "reason": "database_unavailable"}
    if factory is not None:
        with factory() as session:
            cur = session.execute(
                select(JarvisFact).where(
                    JarvisFact.user_id == uid,
                    JarvisFact.fact_type == "jarvis_settings",
                    JarvisFact.key == "proactive_execution_mode",
                ).limit(1)
            ).scalar_one_or_none()
    if cur and (cur.value or "").strip().lower() == "auto":
        return {"ok": True, "upgraded": False, "reason": "already_auto"}
    acted = 0
    ignored = 0
    for at in ("reorder", "collection", "payment"):
        acted += count_recent_outcomes_sync(user_id=uid, alert_type=at, outcome="acted", days=21)
        ignored += count_recent_outcomes_sync(user_id=uid, alert_type=at, outcome="ignored", days=21)
    denom = acted + ignored
    if denom < 8 or acted < 6:
        return {"ok": True, "upgraded": False, "reason": "insufficient_signal"}
    if acted / float(denom) < 0.72:
        return {"ok": True, "upgraded": False, "reason": "acceptance_ratio_low"}
    out = JarvisMemoryEngineLite.store_fact(
        user_id=uid,
        fact_type="jarvis_settings",
        key="proactive_execution_mode",
        value="auto",
        confidence=0.55,
    )
    return {"ok": True, "upgraded": bool(out.get("ok")), "note": "Stored proactive_execution_mode=auto (user may edit)"}


def proactive_noise_cooldown_scale_sync(*, user_id: int, alert_type: str) -> float:
    """Step 5 — reduce frequency weight when user ignores many alerts of one type."""
    from services.jarvis_proactive_intelligence import count_recent_outcomes_sync

    uid = int(user_id)
    ig = count_recent_outcomes_sync(user_id=uid, alert_type=(alert_type or "")[:64], outcome="ignored", days=14)
    n = int(ig or 0)
    if n >= 10:
        return 0.35
    if n >= 6:
        return 0.55
    if n >= 3:
        return 0.75
    return 1.0


class JarvisMemoryEngineLite:
    """Minimal fact writer without importing heavy graph (circular safety)."""

    @staticmethod
    def store_fact(
        *,
        user_id: int,
        fact_type: str,
        key: str,
        value: str,
        confidence: float = 0.7,
    ) -> dict[str, Any]:
        from decimal import Decimal

        from services.jarvis_memory_engine import JarvisMemoryEngine

        return JarvisMemoryEngine().store_fact(
            int(user_id),
            (fact_type or "general").strip()[:64],
            (key or "").strip()[:256],
            (value or "").strip()[:12000],
            "autonomous_agent",
            confidence=float(confidence),
        )


def generate_plan_sync(
    *,
    user_id: int,
    organization_ids: list[int],
) -> list[dict[str, Any]]:
    """Merge active goals + proactive insights into ordered executable steps (metadata)."""
    uid = int(user_id)
    oids = [int(x) for x in organization_ids if int(x) > 0]
    from services.jarvis_goal_engine import auto_continue_incomplete_goals_sync

    plan: list[dict[str, Any]] = []
    for g in auto_continue_incomplete_goals_sync(user_id=uid, limit=3):
        plan.append(
            {
                "kind": "goal_subtask",
                "title": g.get("next_subtask_title") or "Goal step",
                "payload": {"goal_id": g.get("goal_id"), "subtask_id": g.get("next_subtask_id")},
            }
        )
    insights = get_cached_proactive_insights_sync(user_id=uid)
    primary_oid = oids[0] if oids else 0
    for ins in insights[:4]:
        title = str(ins.get("title") or "")
        ar = ins.get("action_ready_payload") if isinstance(ins.get("action_ready_payload"), dict) else {}
        handler = str(ar.get("handler") or "")
        if handler == "create_purchase_order_draft" and primary_oid > 0:
            sku = ""
            if isinstance(ar.get("lines"), list) and ar["lines"]:
                sku = str(ar["lines"][0].get("sku_name") or "")
            if not sku:
                sku = str(ar.get("sku") or "")
            scale = proactive_noise_cooldown_scale_sync(user_id=uid, alert_type="reorder")
            if scale < 0.45:
                continue
            plan.append(
                {
                    "kind": "create_purchase_order_draft",
                    "title": title or f"Reorder {sku}",
                    "payload": {
                        "organization_id": int(ar.get("organization_id") or primary_oid),
                        "sku": sku,
                        "user_id": uid,
                        "quantity_hint": None,
                        "simulation": simulate_reorder_outcome_sync(
                            user_id=uid, organization_id=int(ar.get("organization_id") or primary_oid), sku=sku
                        ),
                    },
                }
            )
        elif handler == "schedule_emi_reminder":
            plan.append({"kind": "schedule_emi_reminder", "title": title or "EMI reminder", "payload": dict(ar)})
    return plan[:8]


def execute_step_sync(*, user_id: int, step: dict[str, Any]) -> dict[str, Any]:
    """Run one plan step with safety gates + learning log."""
    uid = int(user_id)
    kind = str(step.get("kind") or "").strip()
    if not is_safe_autonomous_action(kind):
        log_agent_action_sync(
            user_id=uid,
            action_kind=kind or "unknown",
            outcome="skipped",
            detail={"reason": "forbidden_or_unlisted"},
        )
        return {"ok": False, "skipped": True, "reason": "unsafe_or_unknown_kind"}
    payload = step.get("payload") if isinstance(step.get("payload"), dict) else {}
    from services.jarvis_proactive_action_engine import (
        auto_po_draft_enabled,
        build_reorder_po_draft_payload_sync,
        try_execute_create_po_draft,
        user_execution_mode_for_user,
    )

    if kind == "create_purchase_order_draft":
        oid = int(payload.get("organization_id") or 0)
        sku = str(payload.get("sku") or "").strip()
        if oid <= 0 or not sku:
            log_agent_action_sync(user_id=uid, action_kind=kind, outcome="failed", detail={"error": "missing sku/org"})
            update_learning_stats_sync(user_id=uid, action_kind=kind, outcome="failed")
            return {"ok": False, "error": "missing sku or organization_id"}
        conf = dynamic_confidence_for_action_sync(user_id=uid, action_kind=kind)
        if conf < 0.35:
            log_agent_action_sync(user_id=uid, action_kind=kind, outcome="skipped", detail={"confidence": conf})
            return {"ok": True, "skipped": True, "reason": "low_historical_confidence"}
        sim = payload.get("simulation") if isinstance(payload.get("simulation"), dict) else simulate_reorder_outcome_sync(
            user_id=uid, organization_id=oid, sku=sku
        )
        if "no_supplier" in (sim.get("risk_flags") or []):
            log_agent_action_sync(user_id=uid, action_kind=kind, outcome="failed", detail=sim)
            update_learning_stats_sync(user_id=uid, action_kind=kind, outcome="failed")
            return {"ok": False, "error": "no_supplier", "simulation": sim}
        mode = user_execution_mode_for_user(uid)
        po_payload = build_reorder_po_draft_payload_sync(
            organization_id=oid, sku=sku, user_id=uid, quantity_hint=payload.get("quantity_hint"), supplier_index=0
        )
        if mode != "auto" or not auto_po_draft_enabled():
            log_agent_action_sync(
                user_id=uid,
                action_kind=kind,
                outcome="skipped",
                payload=po_payload,
                detail={"reason": "not_auto_or_po_flag_off", "mode": mode},
            )
            return {"ok": True, "skipped": True, "payload": po_payload, "mode": mode}
        ex = try_execute_create_po_draft(user_id=uid, payload=po_payload)
        if ex and ex.get("executed") and (ex.get("result") or {}).get("ok"):
            log_agent_action_sync(user_id=uid, action_kind=kind, outcome="success", detail=ex)
            update_learning_stats_sync(user_id=uid, action_kind=kind, outcome="success")
            return {"ok": True, "executed": True, "result": ex}
        # Self-correction: alternate supplier (Step 3)
        alt = build_reorder_po_draft_payload_sync(
            organization_id=oid, sku=sku, user_id=uid, quantity_hint=payload.get("quantity_hint"), supplier_index=1
        )
        if alt.get("ok"):
            ex2 = try_execute_create_po_draft(user_id=uid, payload=alt)
            if ex2 and ex2.get("executed") and (ex2.get("result") or {}).get("ok"):
                log_agent_action_sync(
                    user_id=uid,
                    action_kind=kind,
                    outcome="success",
                    detail={**(ex2 or {}), "retry": "alternate_supplier"},
                    retry_count=1,
                )
                update_learning_stats_sync(user_id=uid, action_kind=kind, outcome="success")
                return {"ok": True, "executed": True, "result": ex2, "retry": "alternate_supplier"}
        log_agent_action_sync(
            user_id=uid,
            action_kind=kind,
            outcome="failed",
            detail={"first": ex, "alternate": alt},
            retry_count=1,
        )
        update_learning_stats_sync(user_id=uid, action_kind=kind, outcome="failed")
        return {"ok": False, "error": "po_draft_failed", "detail": ex, "alternate": alt}
    if kind == "schedule_emi_reminder":
        log_agent_action_sync(user_id=uid, action_kind=kind, outcome="partial", payload=payload, detail={"note": "logged_only"})
        update_learning_stats_sync(user_id=uid, action_kind=kind, outcome="partial")
        return {"ok": True, "logged": True}
    if kind == "goal_subtask":
        log_agent_action_sync(user_id=uid, action_kind=kind, outcome="partial", payload=payload)
        return {"ok": True, "nudge": True, "payload": payload}
    log_agent_action_sync(user_id=uid, action_kind=kind, outcome="skipped", detail={"reason": "unhandled_kind"})
    return {"ok": True, "skipped": True}


def run_agent_cycle_sync(*, user_id: int, organization_ids: list[int]) -> dict[str, Any]:
    """
    One autonomous tick: plan → execute safe steps → logs.

    Step 10 — rate-limited per user (default 30 minutes).
    """
    uid = int(user_id)
    oids = [int(x) for x in organization_ids if int(x) > 0]
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    now = time.monotonic()
    last = _LAST_CYCLE_TS.get(uid, 0.0)
    if now - last < _cycle_interval_seconds():
        return {"ok": True, "skipped": "rate_limited", "next_in_sec": round(_cycle_interval_seconds() - (now - last), 1)}
    today = datetime.now(timezone.utc).date().isoformat()
    if _DEDUPE_DAY.get(uid) != today:
        _DEDUPE_FP[uid] = set()
        _DEDUPE_DAY[uid] = today
    fps = _DEDUPE_FP.setdefault(uid, set())
    plan = generate_plan_sync(user_id=uid, organization_ids=oids)
    results: list[dict[str, Any]] = []
    for step in plan:
        fp = _fingerprint(step)
        if fp in fps:
            results.append({"step": step.get("kind"), "skipped": "duplicate"})
            continue
        fps.add(fp)
        results.append(execute_step_sync(user_id=uid, step=step))
    _LAST_CYCLE_TS[uid] = time.monotonic()
    if plan:
        maybe_upgrade_execution_mode_fact_sync(user_id=uid)
    return {"ok": True, "steps": len(plan), "results": results}


def run_continuous_agent(
    user_id: int,
    *,
    organization_ids: list[int] | None = None,
    sleep_seconds: float = 1800.0,
    forever: bool = False,
    max_cycles: int | None = None,
    on_cycle: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Step 2 — run one or more agent cycles.

    * ``forever=True`` only for dedicated worker processes (uses ``sleep`` between ticks).
    * Default: **one** cycle (safe for scripts/tests).
    """
    uid = int(user_id)
    oids = list(organization_ids or [])
    if not oids:
        from services.jarvis_proactive_engine import _org_ids_for_user

        oids = _org_ids_for_user(uid)[:5]
    out: list[dict[str, Any]] = []
    sleep_s = max(60.0, float(sleep_seconds))

    def _emit(res: dict[str, Any]) -> None:
        out.append(res)
        if on_cycle:
            try:
                on_cycle(res)
            except Exception as exc:
                _log.debug("on_cycle hook: %s", exc)

    if forever:
        while True:
            _emit(run_agent_cycle_sync(user_id=uid, organization_ids=oids))
            time.sleep(sleep_s)
    n = max(1, int(max_cycles)) if max_cycles is not None else 1
    for i in range(n):
        _emit(run_agent_cycle_sync(user_id=uid, organization_ids=oids))
        if i < n - 1:
            time.sleep(sleep_s)
    return out


def generate_and_store_daily_plan_sync(*, user_id: int, organization_ids: list[int]) -> dict[str, Any]:
    """Step 8 — persist Today's Plan (business / personal / risks)."""
    uid = int(user_id)
    oids = [int(x) for x in organization_ids if int(x) > 0]
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    today = datetime.now(timezone.utc).date()
    insights = get_cached_proactive_insights_sync(user_id=uid)
    risk = [x for x in insights if "risk" in str(x.get("title", "")).lower() or float(x.get("impact", {}).get("urgency_score") or 0) > 0.85]
    plan_body: dict[str, Any] = {
        "top_business_actions": [x.get("recommended_action") or x.get("title") for x in insights[:3]],
        "top_personal_actions": [x.get("title") for x in insights[3:5]],
        "risk_alerts": [x.get("title") for x in risk[:4]],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization_ids": oids[:5],
    }
    with factory() as session:
        with session.begin():
            existing = session.execute(
                select(JarvisDailyAgentPlan).where(
                    JarvisDailyAgentPlan.user_id == uid,
                    JarvisDailyAgentPlan.plan_date == today,
                ).limit(1)
            ).scalar_one_or_none()
            if existing:
                row = session.get(JarvisDailyAgentPlan, int(existing.id))
                if row:
                    row.payload = plan_body
            else:
                session.add(JarvisDailyAgentPlan(user_id=uid, plan_date=today, payload=plan_body))
    return {"ok": True, "plan": plan_body}


def finalize_agent_day_summary_sync(*, user_id: int, for_date: date | None = None) -> dict[str, Any]:
    """Step 9 — high-importance episodic memory from today's action log."""
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "user_id required"}
    d = for_date or datetime.now(timezone.utc).date()
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    with factory() as session:
        rows = list(
            session.scalars(
                select(JarvisAgentActionLog)
                .where(JarvisAgentActionLog.user_id == uid, JarvisAgentActionLog.created_at >= start, JarvisAgentActionLog.created_at < end)
                .order_by(JarvisAgentActionLog.created_at.desc())
                .limit(80)
            ).all()
        )
    ok = sum(1 for r in rows if r.outcome == "success")
    bad = sum(1 for r in rows if r.outcome == "failed")
    summary = (
        f"Autonomous day summary {d.isoformat()}: successes={ok}, failures={bad}. "
        f"What worked: prioritize low-risk drafts when simulation clean. "
        f"What to improve: reduce retries when supplier list short."
    )
    try:
        from services.jarvis_memory_engine import JarvisMemoryEngine

        JarvisMemoryEngine().store_episode(
            uid,
            "agent_day_close",
            summary[:8000],
            importance=9,
            title=f"Jarvis agent day {d.isoformat()}",
        )
    except Exception as exc:
        _log.warning("finalize_agent_day_summary_sync episode: %s", exc)
        JarvisMemoryEngineLite.store_fact(
            user_id=uid,
            fact_type="agent_episode",
            key=f"day_summary:{d.isoformat()}",
            value=summary[:8000],
            confidence=0.9,
        )
    return {"ok": True, "logged": True, "successes": ok, "failures": bad}


def run_autonomous_cycle_all_users_sync() -> dict[str, Any]:
    """Scheduler entry — one tick per active member user."""
    from sqlalchemy import select as _select

    from core.db.models import UserOrganizationMembership

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no database"}
    with factory() as session:
        uids = list(
            session.scalars(
                _select(UserOrganizationMembership.user_id).where(UserOrganizationMembership.is_active.is_(True)).distinct()
            ).all()
        )
    n = 0
    for uid in uids:
        uid = int(uid)
        if uid <= 0:
            continue
        with factory() as s2:
            oids = [
                int(x)
                for x in s2.scalars(
                    _select(UserOrganizationMembership.organization_id).where(
                        UserOrganizationMembership.user_id == uid,
                        UserOrganizationMembership.is_active.is_(True),
                    )
                ).all()
            ]
        try:
            run_agent_cycle_sync(user_id=uid, organization_ids=oids[:5])
            n += 1
        except Exception as exc:
            _log.warning("autonomous_cycle user=%s: %s", uid, exc)
    return {"ok": True, "users_processed": n}


def run_jarvis_autonomous_morning_bundle_sync() -> dict[str, Any]:
    """Morning: persist Today's Plan for each active user (Step 8), then one agent tick."""
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no database"}
    from sqlalchemy import select as _select

    from core.db.models import UserOrganizationMembership

    plans = 0
    with factory() as session:
        uids = list(
            session.scalars(
                _select(UserOrganizationMembership.user_id).where(UserOrganizationMembership.is_active.is_(True)).distinct()
            ).all()
        )
    for uid in uids:
        uid = int(uid)
        if uid <= 0:
            continue
        with factory() as s2:
            oids = [
                int(x)
                for x in s2.scalars(
                    _select(UserOrganizationMembership.organization_id).where(
                        UserOrganizationMembership.user_id == uid,
                        UserOrganizationMembership.is_active.is_(True),
                    )
                ).all()
            ]
        try:
            generate_and_store_daily_plan_sync(user_id=uid, organization_ids=oids[:5])
            plans += 1
        except Exception as exc:
            _log.debug("daily_plan user=%s: %s", uid, exc)
    cyc = run_autonomous_cycle_all_users_sync()
    return {"ok": True, "daily_plans_written": plans, "autonomous_cycle": cyc}


def cluster_top_insights_sync(*, user_id: int, top_n: int = 3) -> dict[str, Any]:
    """Step 6 — UI-friendly cluster + cap (delegates to narrative layer)."""
    from services.jarvis_narrative import cluster_critical_insights_sync

    uid = int(user_id)
    ins = get_cached_proactive_insights_sync(user_id=uid)
    return cluster_critical_insights_sync(ins, top_n=top_n)


def record_goal_long_term_learning_sync(*, user_id: int) -> dict[str, Any]:
    """
    Step 7 — track goal completion rate for long-horizon adaptation (stored in ``JarvisFact``).
    """
    uid = int(user_id)
    if uid <= 0:
        return {"ok": False, "error": "invalid user"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no database"}
    from core.db.models import JarvisGoal

    with factory() as session:
        total = int(
            session.scalar(select(func.count()).select_from(JarvisGoal).where(JarvisGoal.user_id == uid)) or 0
        )
        done = int(
            session.scalar(
                select(func.count())
                .select_from(JarvisGoal)
                .where(JarvisGoal.user_id == uid, JarvisGoal.status == "completed")
            )
            or 0
        )
    rate = round(done / max(1, total), 4)
    blob = json.dumps({"goals_total": total, "goals_completed": done, "completion_rate": rate, "as_of": datetime.now(timezone.utc).isoformat()})[
        :12000
    ]
    now = datetime.now(timezone.utc)
    try:
        with factory() as session:
            with session.begin():
                row = session.execute(
                    select(JarvisFact).where(
                        JarvisFact.user_id == uid,
                        JarvisFact.fact_type == "agent_learning",
                        JarvisFact.key == "goal_long_term_stats",
                    ).limit(1)
                ).scalar_one_or_none()
                if row:
                    r2 = session.get(JarvisFact, row.id)
                    if r2:
                        r2.value = blob
                        r2.last_verified = now
                else:
                    session.add(
                        JarvisFact(
                            user_id=uid,
                            fact_type="agent_learning",
                            key="goal_long_term_stats",
                            value=blob,
                            confidence=Decimal("0.7"),
                            source="autonomous_agent",
                            last_verified=now,
                        )
                    )
    except Exception as exc:
        _log.debug("record_goal_long_term_learning_sync: %s", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "completion_rate": rate, "goals_total": total, "goals_completed": done}
