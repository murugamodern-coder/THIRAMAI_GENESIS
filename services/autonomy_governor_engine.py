"""
Dynamic autonomy governor:
- computes auto/semi/assist execution mode from trust/risk/confidence/failures
- restricts execution depth for unstable conditions
"""

from __future__ import annotations

from typing import Any

from services.feedback_engine import calculate_prediction_accuracy
from services.meta_autonomy_engine import monitor_system_performance


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _dynamic_thresholds(*, user_id: int, organization_id: int) -> dict[str, float]:
    perf = monitor_system_performance(user_id=int(user_id), organization_id=int(organization_id), hours=24 * 7)
    fb = calculate_prediction_accuracy(int(user_id), limit=250)
    fr = _safe_float(perf.get("failure_rate"), 0.0)
    trust = _safe_float(fb.get("system_trust_score"), 50.0)
    # Feedback loop: adapt minimum trust threshold from observed quality.
    trust_auto = 60.0 + (5.0 if fr > 0.30 else 0.0) + (3.0 if trust < 45.0 else 0.0)
    trust_semi = 45.0 + (5.0 if fr > 0.35 else 0.0)
    return {
        "trust_min_auto": max(40.0, min(85.0, trust_auto)),
        "trust_min_semi": max(30.0, min(75.0, trust_semi)),
        "plan_conf_min": 0.60,
        "repeated_failure_rate_limit": 0.40,
    }


def _domain_success_rate(
    *,
    user_id: int,
    organization_id: int,
    domain: str,
) -> float:
    perf = monitor_system_performance(user_id=int(user_id), organization_id=int(organization_id), hours=24 * 14)
    for row in list(perf.get("domain_success_rates") or []):
        if str(row.get("domain") or "") == str(domain or ""):
            return _safe_float(row.get("success_rate"), 50.0)
    return 50.0


def _controlled_freedom_zone(*, allow: bool, mode: str, risk: float) -> str:
    m = str(mode or "assist").lower()
    r = float(risk or 0.0)
    if not allow or m == "assist" or r >= 75.0:
        return "RESTRICTED_ZONE"
    if m == "semi" or r >= 45.0:
        return "CONTROLLED_ZONE"
    return "SAFE_ZONE"


def compute_autonomy_decision(
    *,
    user_id: int,
    organization_id: int,
    domain: str,
    system_trust_score: float,
    action_risk_score: float,
    plan_confidence_score: float,
    recent_failure_rate: float,
    repeated_failure_rate: float,
    style: str = "balanced",
    active_triggers: list[dict[str, Any]] | None = None,
    identity_context: dict[str, Any] | None = None,
    mission_importance: float | None = None,
) -> dict[str, Any]:
    thresholds = _dynamic_thresholds(user_id=int(user_id), organization_id=int(organization_id))
    domain_success = _domain_success_rate(
        user_id=int(user_id),
        organization_id=int(organization_id),
        domain=str(domain or "general"),
    )
    trust = _safe_float(system_trust_score, 50.0)
    risk = _safe_float(action_risk_score, 0.0)
    plan_conf = _safe_float(plan_confidence_score, 0.0)
    fail_rate = _safe_float(recent_failure_rate, 0.0)
    rep_fail = _safe_float(repeated_failure_rate, 0.0)
    sty = str(style or "balanced").lower()
    triggers = [t for t in (active_triggers or []) if isinstance(t, dict)]
    identity = identity_context if isinstance(identity_context, dict) else {}
    mission_priority = max(0.0, min(1.0, _safe_float(mission_importance, 0.0)))
    identity_adjustments: list[str] = []

    mode = "auto"
    allow = True
    reasons: list[str] = []
    risk_level = "low" if risk < 35 else ("medium" if risk <= 80 else "high")
    max_execution_depth = 99

    high_risk_cutoff = 80.0 if sty == "balanced" else (85.0 if sty == "aggressive" else 72.0)
    if risk > high_risk_cutoff:
        allow = False
        mode = "assist"
        max_execution_depth = 0
        reasons.append("risk_score_above_80_requires_explicit_confirmation")
    trust_auto_min = thresholds["trust_min_auto"] + (4.0 if sty == "conservative" else (-3.0 if sty == "aggressive" else 0.0))
    trust_semi_min = thresholds["trust_min_semi"] + (3.0 if sty == "conservative" else (-2.0 if sty == "aggressive" else 0.0))
    if trust < trust_auto_min:
        mode = "semi"
        reasons.append("trust_below_auto_threshold")
    if trust < trust_semi_min:
        mode = "assist"
        allow = False
        max_execution_depth = 0
        reasons.append("trust_below_semi_threshold")
    if plan_conf < thresholds["plan_conf_min"]:
        mode = "assist"
        allow = False
        max_execution_depth = 0
        reasons.append("plan_confidence_below_threshold")
    if fail_rate >= 0.30:
        if mode == "auto":
            mode = "semi"
        reasons.append("recent_failure_rate_high")
    strategy_blocked = False
    if rep_fail >= thresholds["repeated_failure_rate_limit"]:
        if mode == "auto":
            mode = "semi"
        max_execution_depth = min(max_execution_depth, 1)
        reasons.append("repeated_failures_restrict_execution_depth")
    if rep_fail >= 0.55:
        # Failure intelligence: stop early when repeated failure signal is strong.
        allow = False
        mode = "assist"
        max_execution_depth = 0
        strategy_blocked = True
        reasons.append("repeated_failures_escalated_to_assist")
    if any(str(t.get("type") or "") == "risk_spike" for t in triggers):
        mode = "assist"
        allow = False
        max_execution_depth = 0
        reasons.append("realtime_risk_spike_trigger")
    elif any(str(t.get("type") or "") == "environment_shift" for t in triggers):
        if mode == "auto":
            mode = "semi"
        max_execution_depth = min(max_execution_depth, 2)
        reasons.append("realtime_environment_shift_trigger")
    elif any(str(t.get("type") or "") == "opportunity_spike" for t in triggers):
        reasons.append("realtime_opportunity_spike_trigger")
        # Controlled opportunity exploitation: only when trust high + risk moderate.
        if trust >= max(65.0, trust_auto_min) and 35.0 <= risk <= 65.0 and fail_rate < 0.25 and not strategy_blocked:
            if mode != "assist":
                mode = "auto"
                allow = True
                max_execution_depth = max(max_execution_depth, 4 if sty != "conservative" else 3)
                reasons.append("controlled_aggressive_mode_for_opportunity_spike")
    if domain_success < 50.0 and mode == "auto":
        mode = "semi"
        reasons.append("domain_success_rate_low")

    # Mission-aware adjustments (never bypass hard blocks set above).
    if mission_priority >= 0.70 and allow and mode != "assist":
        if mode == "semi" and risk <= 55.0 and trust >= trust_semi_min:
            max_execution_depth = max(max_execution_depth, 2 if sty == "conservative" else 3)
            reasons.append("mission_priority_depth_boost")
            identity_adjustments.append("increased_semi_depth_for_high_mission_priority")
        if mode == "auto" and risk <= 60.0 and trust >= trust_auto_min:
            max_execution_depth = max(max_execution_depth, 4 if sty != "conservative" else 3)
            reasons.append("mission_priority_auto_depth_boost")
            identity_adjustments.append("increased_auto_depth_for_high_mission_priority")

    if mode == "semi" and max_execution_depth > 3:
        max_execution_depth = 4 if sty == "aggressive" else (2 if sty == "conservative" else 3)
    if mode == "assist":
        max_execution_depth = 0

    # HARD BLOCK: once execution is disallowed, never re-enable it.
    if not allow:
        mode = "assist"
        max_execution_depth = 0

    return {
        "allow_execute": bool(allow),
        "mode": mode,
        "autonomy_zone": _controlled_freedom_zone(allow=bool(allow), mode=mode, risk=risk),
        "reason": "; ".join(reasons) if reasons else "healthy_signals_for_execution",
        "risk_level": risk_level,
        "risk_score": round(risk, 2),
        "max_execution_depth": int(max_execution_depth),
        "retry_policy": {
            "strategy_blocked": bool(strategy_blocked),
            "max_retry_depth": 0 if strategy_blocked else (1 if rep_fail >= thresholds["repeated_failure_rate_limit"] else 2),
        },
        "thresholds": thresholds,
        "signals": {
            "system_trust_score": round(trust, 2),
            "domain_success_rate": round(domain_success, 2),
            "plan_confidence_score": round(plan_conf, 3),
            "recent_failure_rate": round(fail_rate, 4),
            "repeated_failure_rate": round(rep_fail, 4),
            "style": sty,
            "active_triggers": triggers,
        },
        "identity_context": identity,
        "mission_importance": round(mission_priority, 4),
        "identity_adjustments": identity_adjustments,
    }


def apply_governor_mode_to_plan(
    plan_steps: list[dict[str, Any]],
    *,
    autonomy_decision: dict[str, Any],
) -> list[dict[str, Any]]:
    mode = str((autonomy_decision or {}).get("mode") or "auto")
    if mode == "auto":
        return list(plan_steps or [])
    if mode == "assist":
        return []
    depth = max(1, int((autonomy_decision or {}).get("max_execution_depth") or 2))
    ordered = sorted(list(plan_steps or []), key=lambda x: int(x.get("step_order") or 0))
    return ordered[:depth]
