"""P2 intelligence layer: pattern memory, adaptive planning, safe improvement tasks."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import DomainDominionProfile
from services.execution_memory_store import build_system_failure_playbook
from services.learning_engine import analyze_patterns, get_strategy_profiles
from services.meta_autonomy_engine import generate_self_improvement_tasks, self_correction_triggers


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def decision_memory_context(*, user_id: int, organization_id: int, limit: int = 25) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"recent_decisions": [], "recent_outcomes": [], "decision_bias": "neutral"}
    with fn() as session:
        row = session.execute(
            select(DomainDominionProfile).where(
                DomainDominionProfile.user_id == int(user_id),
                DomainDominionProfile.organization_id == int(organization_id),
            )
        ).scalar_one_or_none()
    if row is None:
        return {"recent_decisions": [], "recent_outcomes": [], "decision_bias": "neutral"}
    meta = dict(row.meta_json or {})
    mem = meta.get("agent_identity_memory") if isinstance(meta.get("agent_identity_memory"), dict) else {}
    dec = list(mem.get("decisions") or [])[-max(1, int(limit)) :]
    out = list(mem.get("outcomes") or [])[-max(1, int(limit)) :]
    win_rate = (
        sum(1 for x in out if isinstance(x, dict) and bool(x.get("success"))) / max(1, len(out))
        if out
        else 0.5
    )
    if win_rate >= 0.65:
        bias = "exploit"
    elif win_rate <= 0.40:
        bias = "defensive"
    else:
        bias = "balanced"
    return {
        "recent_decisions": dec,
        "recent_outcomes": out,
        "decision_bias": bias,
        "decision_success_rate": round(float(win_rate), 3),
    }


def build_pattern_intelligence(*, user_id: int, organization_id: int) -> dict[str, Any]:
    insights = analyze_patterns(int(user_id), limit=260)
    profiles = get_strategy_profiles(int(user_id))
    playbook = build_system_failure_playbook(
        user_id=int(user_id),
        organization_id=int(organization_id),
        limit=280,
        min_cluster_count=2,
    )
    best = [x for x in list(insights.get("best_strategies") or []) if isinstance(x, dict)]
    worst = [x for x in list(insights.get("worst_patterns") or []) if isinstance(x, dict)]
    reusable = [str(x.get("source_type") or "") for x in best if float(x.get("score") or 0.0) >= 0.60]
    suppressed = [str(x.get("source_type") or "") for x in worst if float(x.get("score") or 1.0) <= 0.40]
    clusters: list[dict[str, Any]] = []
    for row in list(playbook.get("clusters") or []):
        if not isinstance(row, dict):
            continue
        count = int(row.get("count") or 0)
        confidence = min(0.99, float(count) / 6.0) if count > 0 else 0.0
        clusters.append(
            {
                "step_kind": str(row.get("step_kind") or ""),
                "error_class": str(row.get("error_class") or "unknown"),
                "domain": str(row.get("domain") or "general"),
                "count": count,
                "confidence": round(confidence, 3),
                "suppressed": bool(count >= 3 and confidence >= 0.65),
            }
        )
    return {
        "ok": bool(insights.get("ok")),
        "learning_insights": insights,
        "strategy_profiles": profiles,
        "failure_playbook": playbook,
        "reusable_strategies": reusable[:10],
        "suppressed_strategies": suppressed[:10],
        "suppression_clusters": clusters[:30],
    }


def adapt_plan_with_intelligence(
    plan_steps: list[dict[str, Any]],
    *,
    pattern_intelligence: dict[str, Any],
    domain_context: dict[str, Any],
    realtime_events: dict[str, Any],
    decision_memory: dict[str, Any],
) -> list[dict[str, Any]]:
    reusable = set(str(x) for x in list(pattern_intelligence.get("reusable_strategies") or []))
    suppression_clusters = [
        x for x in list(pattern_intelligence.get("suppression_clusters") or []) if isinstance(x, dict)
    ]
    triggers = list(realtime_events.get("triggers") or [])
    risk_spike = any(str(t.get("type") or "") == "risk_spike" for t in triggers if isinstance(t, dict))
    opp_spike = any(str(t.get("type") or "") == "opportunity_spike" for t in triggers if isinstance(t, dict))
    out: list[dict[str, Any]] = []
    for row in list(plan_steps or []):
        if not isinstance(row, dict):
            continue
        step = dict(row)
        payload = dict(step.get("payload") or {})
        sk = str(step.get("step_kind") or "")
        source_hint = "execution" if sk.startswith(("plugin_", "browser_")) else "internal"
        domain = str(domain_context.get("domain") or "general")
        matched_clusters = [
            c
            for c in suppression_clusters
            if bool(c.get("suppressed"))
            and str(c.get("step_kind") or "") == sk
            and str(c.get("domain") or "") == domain
        ]
        cluster_suppressed = bool(matched_clusters)
        payload["decision_memory_bias"] = str(decision_memory.get("decision_bias") or "balanced")
        payload["domain_context_light"] = {
            "domain": str(domain_context.get("domain") or "general"),
            "profile_enabled": bool(domain_context.get("profile_enabled", True)),
        }
        payload["adaptive_signals"] = {
            "risk_spike": bool(risk_spike),
            "opportunity_spike": bool(opp_spike),
        }
        payload["strategy_reuse_enabled"] = bool(source_hint in reusable)
        payload["strategy_suppressed"] = cluster_suppressed
        payload["suppression_cluster"] = matched_clusters[0] if matched_clusters else None
        if str(decision_memory.get("decision_bias") or "") == "defensive" and not cluster_suppressed:
            payload["automatic_strategy_swap"] = "conservative_fallback_profile"
        if cluster_suppressed and str(step.get("risk_level") or "").lower() == "high":
            step["risk_level"] = "medium"
            payload.setdefault("alternative_paths", []).append(
                {"step_kind": "plugin_notify", "payload": {"title": "Suppressed risky strategy", "body": "Fallback to assisted path", "severity": "warning"}}
            )
        if risk_spike and not sk.startswith("internal_"):
            if str(step.get("risk_level") or "").lower() == "high":
                step["risk_level"] = "medium"
        if opp_spike and not sk.startswith("internal_"):
            payload["opportunity_mode"] = True
        step["payload"] = payload
        out.append(step)
    return out


def safe_self_improvement_backlog(*, user_id: int, organization_id: int) -> dict[str, Any]:
    raw = generate_self_improvement_tasks(user_id=int(user_id), organization_id=int(organization_id))
    sc = self_correction_triggers(user_id=int(user_id), organization_id=int(organization_id))
    tasks = [x for x in list(raw.get("tasks") or []) if isinstance(x, dict)]
    safe = []
    for t in tasks:
        ttype = str(t.get("task_type") or "")
        safe.append(
            {
                **t,
                "execution_mode": "assist_only",
                "safe_to_auto_apply": ttype in {"retry_optimization"},
            }
        )
    return {
        "ok": bool(raw.get("ok")),
        "tasks": safe[:12],
        "gaps": raw.get("gaps"),
        "self_correction_triggers": list(sc.get("self_correction_triggers") or []),
    }
