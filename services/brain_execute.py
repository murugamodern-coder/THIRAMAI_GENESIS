"""
Central orchestration: intent → plan → ``preflight_plan_execution_safety`` (governance +
per-step autonomy classification) → persisted run → ``execute_action_plan`` (via
``run_persisted_action_plan``, the only path that performs steps).

Does not call plugins or step dispatch directly.
"""

from __future__ import annotations

import json
import os
import time
from uuid import uuid4
from typing import Any

from sqlalchemy import func, select

from core.db.session_utils import get_session_factory_safe
from core.db.models import ActionExecutionRun
from core.execution_contract_guard import (
    PipelineViolationError,
    activate_execution_context,
    assert_pipeline_sequence,
    clear_execution_context,
    mark_pipeline_stage,
)
from services.action_execution_engine import (
    ActionExecutionContext,
    create_action_execution_run,
    preflight_plan_execution_safety,
    run_persisted_action_plan,
)
from services.agent_identity_continuity_engine import (
    apply_style_to_plan,
    get_agent_profile,
    mission_alignment_score,
    record_identity_memory,
)
from services.autonomy_governor_engine import apply_governor_mode_to_plan, compute_autonomy_decision
from services.domain_execution_intelligence import load_domain_execution_context
from services.execution_capability_registry import get_execution_capabilities
from services.event_listener_engine import detect_realtime_triggers
from services.feedback_engine import calculate_prediction_accuracy
from services.intent_classifier import classify_intent
from services.identity_context_loader import (
    compute_identity_influence,
    load_master_identity_context,
    score_long_term_alignment,
)
from services.lifecycle_state import lifecycle_from_brain_fields
from services.multi_agent_orchestrator import multi_agent_orchestrator
from services.meta_autonomy_engine import monitor_system_performance
from services.p2_intelligence import (
    adapt_plan_with_intelligence,
    build_pattern_intelligence,
    decision_memory_context,
    safe_self_improvement_backlog,
)
from services.proactive_autonomy_engine import generate_controlled_self_goals
from services.proactive_autonomy_engine import global_priority_engine
from services.governance_engine import is_kill_switch_active
from services.execution_closure_engine import handle_execution_closure
from services.task_decomposition import build_plan_steps_from_command
from services.value_generation_engine import run_value_generation_cycle


def _zero_confidence() -> dict[str, Any]:
    return {
        "score": 0.0,
        "success_rate": 0.0,
        "retries": 0,
        "time_s": 0.0,
        "failed_steps": 0,
    }


def _attach_safety_to_plan(plan_steps: list[dict[str, Any]], preview_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_order = {int(s.get("step_order") or 0): s for s in preview_steps}
    out: list[dict[str, Any]] = []
    for row in plan_steps:
        o = int(row.get("step_order") or 0)
        out.append({**row, "safety": dict(by_order.get(o) or {})})
    return out


def _status_from_result(res: dict[str, Any]) -> str:
    if res.get("partial"):
        return "partial"
    if res.get("ok") is True:
        return "success"
    return "failed"


def _session_factory_or_none():
    return get_session_factory_safe()


def _system_mode() -> str:
    mode = (os.getenv("THIRAMAI_SYSTEM_MODE") or "normal_mode").strip().lower()
    if mode not in {"safe_mode", "normal_mode", "aggressive_mode"}:
        return "normal_mode"
    return mode


def _user_limits(user_id: int) -> dict[str, int]:
    base = {
        "max_parallel_runs": int((os.getenv("THIRAMAI_MAX_PARALLEL_RUNS_DEFAULT") or "3").strip() or 3),
        "max_retry_depth": int((os.getenv("THIRAMAI_MAX_RETRY_DEPTH_DEFAULT") or "2").strip() or 2),
        "max_daily_actions": int((os.getenv("THIRAMAI_MAX_DAILY_ACTIONS_DEFAULT") or "250").strip() or 250),
    }
    raw = (os.getenv("THIRAMAI_USER_AUTONOMY_LIMITS_JSON") or "").strip()
    if not raw:
        return base
    try:
        cfg = json.loads(raw)
    except Exception:
        return base
    per_user = cfg.get(str(int(user_id))) if isinstance(cfg, dict) else None
    if not isinstance(per_user, dict):
        return base
    out = dict(base)
    for k in ("max_parallel_runs", "max_retry_depth", "max_daily_actions"):
        try:
            out[k] = max(1, int(per_user.get(k) or out[k]))
        except Exception:
            continue
    return out


def _current_usage(*, user_id: int, organization_id: int) -> dict[str, int]:
    from datetime import datetime, timezone

    fn = _session_factory_or_none()
    if fn is None:
        return {"parallel_runs": 0, "daily_actions": 0}
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with fn() as session:
        parallel = int(
            session.execute(
                select(func.count(ActionExecutionRun.id)).where(
                    ActionExecutionRun.user_id == int(user_id),
                    ActionExecutionRun.organization_id == int(organization_id),
                    ActionExecutionRun.status.in_(["planned", "awaiting_confirmation", "running"]),
                )
            ).scalar_one()
        )
        daily = int(
            session.execute(
                select(func.count(ActionExecutionRun.id)).where(
                    ActionExecutionRun.user_id == int(user_id),
                    ActionExecutionRun.organization_id == int(organization_id),
                    ActionExecutionRun.created_at >= day_start,
                )
            ).scalar_one()
        )
    return {"parallel_runs": parallel, "daily_actions": daily}


def _tokens(text: str) -> set[str]:
    import re

    return {t for t in re.findall(r"[a-z0-9_]+", str(text or "").lower()) if len(t) >= 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    uni = len(a.union(b))
    if uni <= 0:
        return 0.0
    return float(inter / uni)


def _build_execution_history_context(*, user_id: int, organization_id: int, command: str) -> dict[str, Any]:
    fn = _session_factory_or_none()
    if fn is None:
        return {"previous_attempts": 0, "previous_outcomes": [], "retry_strategy_hint": "normal"}
    cmd_tokens = _tokens(command)
    with fn() as session:
        rows = (
            session.execute(
                select(ActionExecutionRun)
                .where(
                    ActionExecutionRun.user_id == int(user_id),
                    ActionExecutionRun.organization_id == int(organization_id),
                )
                .order_by(ActionExecutionRun.updated_at.desc(), ActionExecutionRun.id.desc())
                .limit(60)
            )
            .scalars()
            .all()
        )
    similar: list[dict[str, Any]] = []
    for r in rows:
        src = str(r.source_command or "")
        sim = _jaccard(cmd_tokens, _tokens(src))
        if sim < 0.22:
            continue
        meta = r.meta_json if isinstance(r.meta_json, dict) else {}
        cl = meta.get("execution_closure") if isinstance(meta.get("execution_closure"), dict) else {}
        similar.append(
            {
                "run_id": int(r.id),
                "similarity": round(sim, 4),
                "command": src[:280],
                "status": str(r.status or ""),
                "final_status": str(cl.get("final_status") or ""),
                "outcome_assessment": str(cl.get("outcome_assessment") or meta.get("outcome_assessment") or ""),
                "failure_reason": str((meta.get("execution_failure") or {}).get("reason") or "")[:220]
                if isinstance(meta.get("execution_failure"), dict)
                else "",
            }
        )
    similar.sort(key=lambda x: float(x.get("similarity") or 0.0), reverse=True)
    top = similar[:8]
    fail_n = sum(
        1
        for x in top
        if str(x.get("final_status") or "").lower() == "failed"
        or str(x.get("status") or "").lower() == "failed"
        or str(x.get("outcome_assessment") or "").lower() == "mismatch"
    )
    attempts = len(top)
    if attempts >= 4 and fail_n / max(1, attempts) >= 0.60:
        hint = "conservative_retry"
    elif fail_n == 0 and attempts >= 2:
        hint = "normal_retry"
    else:
        hint = "normal"
    return {
        "previous_attempts": attempts,
        "previous_outcomes": top,
        "retry_strategy_hint": hint,
    }


def _complexity_score(command: str) -> float:
    c = str(command or "").strip().lower()
    if not c:
        return 0.0
    conj = sum(1 for t in (" and ", " then ", " after ", ";", ",") if t in c)
    cues = sum(1 for t in ("workflow", "pipeline", "strategy", "research", "compare", "execute", "multi-step") if t in c)
    risky = sum(1 for t in ("pay", "trade", "transfer", "deploy", "delete", "contract") if t in c)
    size_component = min(0.35, len(c) / 700.0)
    raw = (0.15 * min(4, conj)) + (0.12 * min(5, cues)) + (0.12 * min(4, risky)) + size_component
    return max(0.05, min(0.99, round(raw, 3)))


def _thinking_depth_profile(command: str) -> dict[str, Any]:
    score = _complexity_score(command)
    if score <= 0.34:
        mode = "shallow"
    elif score <= 0.66:
        mode = "balanced"
    else:
        mode = "deep"
    return {"complexity_score": score, "thinking_depth": mode}


def _normalize_decision_context(
    *,
    intent: str,
    mission_alignment: float,
    plan_confidence_score: float,
    trust_score: float,
    recent_failure_rate: float,
    identity_influence: float,
    long_term_alignment: float,
) -> dict[str, Any]:
    return {
        "intent": str(intent or "").strip().lower(),
        "mission_alignment": round(max(0.0, min(1.0, float(mission_alignment or 0.0))), 3),
        "plan_confidence_score": round(max(0.0, min(1.0, float(plan_confidence_score or 0.0))), 3),
        "trust_score": round(max(0.0, min(100.0, float(trust_score or 0.0))), 2),
        "recent_failure_rate": round(max(0.0, min(1.0, float(recent_failure_rate or 0.0))), 4),
        "identity_influence": round(max(0.0, min(1.0, float(identity_influence or 0.0))), 4),
        "long_term_alignment": round(max(0.0, min(1.0, float(long_term_alignment or 0.0))), 4),
    }


def _signal_fusion_vector(
    *,
    kill_switch_active: bool,
    governor_mode: str,
    mission_alignment: float,
    roi_hint: float,
    memory_hint: float,
) -> dict[str, Any]:
    # Priority order is fixed by weights: safety > governor > mission > ROI > memory.
    weights = {
        "safety": 1.0,
        "governor": 0.8,
        "mission_alignment": 0.55,
        "roi": 0.35,
        "memory_pattern": 0.25,
    }
    normalized = {
        "safety": 0.0 if kill_switch_active else 1.0,
        "governor": 0.2 if str(governor_mode or "").lower() == "assist" else (0.55 if str(governor_mode or "").lower() == "semi" else 0.9),
        "mission_alignment": max(0.0, min(1.0, float(mission_alignment or 0.0))),
        "roi": max(0.0, min(1.0, float(roi_hint or 0.0))),
        "memory_pattern": max(0.0, min(1.0, float(memory_hint or 0.0))),
    }
    weighted = {k: round(weights[k] * normalized[k], 4) for k in weights}
    total = sum(weighted.values())
    confidence = round(total / max(1e-6, sum(weights.values())), 4)
    return {
        "weights": weights,
        "normalized_signals": normalized,
        "weighted_vector": weighted,
        "decision_confidence": confidence,
    }


def _build_execution_summary(
    *,
    reason: str,
    decision_context: dict[str, Any],
    signal_fusion: dict[str, Any],
    thinking_profile: dict[str, Any],
) -> dict[str, Any]:
    top_signals = sorted(
        list((signal_fusion.get("weighted_vector") or {}).items()),
        key=lambda x: float(x[1]),
        reverse=True,
    )[:3]
    return {
        "why": str(reason or "decision_pipeline_completed"),
        "influential_signals": [{"signal": str(k), "score": float(v)} for k, v in top_signals],
        "final_confidence": float(signal_fusion.get("decision_confidence") or 0.0),
        "thinking_depth": str(thinking_profile.get("thinking_depth") or "balanced"),
        "complexity_score": float(thinking_profile.get("complexity_score") or 0.0),
        "decision_context": decision_context,
    }


def _identity_trace(
    *,
    mission_alignment_score: float,
    identity_influence: float,
    long_term_alignment: float,
    identity_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mission_alignment_score": round(max(0.0, min(1.0, float(mission_alignment_score or 0.0))), 4),
        "identity_influence": round(max(0.0, min(1.0, float(identity_influence or 0.0))), 4),
        "long_term_alignment": round(max(0.0, min(1.0, float(long_term_alignment or 0.0))), 4),
        "identity_context": identity_context if isinstance(identity_context, dict) else {},
    }


def _with_identity_trace(
    payload: dict[str, Any],
    *,
    mission_alignment_score: float,
    identity_influence: float,
    long_term_alignment: float,
    identity_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        **payload,
        **_identity_trace(
            mission_alignment_score=mission_alignment_score,
            identity_influence=identity_influence,
            long_term_alignment=long_term_alignment,
            identity_context=identity_context,
        ),
    }


def brain_execute(command: str, user_id: int, organization_id: int) -> dict[str, Any]:
    """
    1. Parse intent from *command*.
    2. Build steps with ``build_plan_steps_from_command``.
    3. ``preflight_plan_execution_safety`` (governance + ``classify_action_step`` per step + budget + sim).
    4. Persist run and execute **only** through ``run_persisted_action_plan`` → ``execute_action_plan``.
    """
    cmd = str(command or "").strip()
    t0 = time.perf_counter()
    execution_trace_id = f"brain-{int(user_id)}-{int(organization_id)}-{uuid4()}"
    thinking = _thinking_depth_profile(cmd)
    identity_ctx = load_master_identity_context()
    long_term_alignment = score_long_term_alignment(cmd, identity_ctx)
    mission_alignment = 0.0
    identity_influence = compute_identity_influence(
        mission_alignment_score=mission_alignment,
        long_term_alignment=long_term_alignment,
        identity_ctx=identity_ctx,
    )
    if not cmd:
        return _with_identity_trace({
            "intent": "unknown",
            "plan": [],
            "result": {"ok": False, "error": "command_empty"},
            "confidence": _zero_confidence(),
            "status": "failed",
            "lifecycle_state": "failed",
            "execution_trace_id": execution_trace_id,
            "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)
    kill_switch_on = is_kill_switch_active(int(user_id))
    if kill_switch_on:
        blocked_result = {
            "ok": False,
            "assist_only": True,
            "reason": "kill_switch_enabled",
            "suggestion": "Execution is disabled by operator kill switch.",
        }
        return _with_identity_trace({
            "intent": "unknown",
            "plan": [],
            "result": blocked_result,
            "confidence": _zero_confidence(),
            "status": "assist",
            "lifecycle_state": "assist",
            "execution_trace_id": execution_trace_id,
            "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)

    intent = classify_intent(cmd)
    mark_pipeline_stage("brain_execute")
    fast_path = bool(str(thinking.get("thinking_depth") or "") == "shallow")
    collab = (
        {
            "ok": True,
            "complex_goal": False,
            "subtasks": [cmd[:280]],
            "assignments": [],
            "shared_memory": {"messages": [], "mode": "fast_path"},
            "outputs": [],
            "proposal_outputs": [],
            "critiques": [],
            "final_synthesis": {
                "summary": "Fast-path synthesis for low-complexity command.",
                "confidence": 0.7,
                "consensus_score": 0.7,
                "conflicts": [],
                "conflict_resolution": "fast_path_non_conflicting",
                "prioritized_decision": {"priority": "medium", "action": "execute_primary_plan"},
                "fallback_option": {"action": "run_safe_fallback", "path": "notify_and_summarize"},
                "risk_tradeoff_explanation": "Low complexity command; avoid unnecessary orchestration overhead.",
                "executable_plan": [],
            },
        }
        if fast_path
        else multi_agent_orchestrator(
            user_id=int(user_id),
            organization_id=int(organization_id),
            goal=cmd,
            context={"intent": intent, "source": "brain_execute"},
        )
    )
    collab_hint = (collab.get("final_synthesis") if isinstance(collab.get("final_synthesis"), dict) else {})
    agent_profile = get_agent_profile(user_id=int(user_id), organization_id=int(organization_id))
    mission_alignment = mission_alignment_score(cmd, agent_profile)
    identity_influence = compute_identity_influence(
        mission_alignment_score=mission_alignment,
        long_term_alignment=long_term_alignment,
        identity_ctx=identity_ctx,
    )
    domain_ctx = load_domain_execution_context(
        user_id=int(user_id),
        organization_id=int(organization_id),
        command=cmd,
        context={"intent": intent, "multi_agent_synthesis": collab_hint, "agent_identity": identity_ctx},
    )
    if isinstance(domain_ctx, dict):
        domain_ctx = {**domain_ctx, "agent_identity": identity_ctx}
    capability_ctx = get_execution_capabilities(
        user_id=int(user_id),
        organization_id=int(organization_id),
        command=cmd,
    )
    realtime_events = detect_realtime_triggers(
        user_id=int(user_id),
        organization_id=int(organization_id),
    )
    history_ctx = _build_execution_history_context(
        user_id=int(user_id),
        organization_id=int(organization_id),
        command=cmd,
    )
    self_goals = (
        {"proposed_goals": [], "goal_confidence": 0.0, "mode": "fast_path_skip"}
        if fast_path
        else generate_controlled_self_goals(
            user_id=int(user_id),
            organization_id=int(organization_id),
            limit=8,
        )
    )
    global_priority = (
        {"ok": True, "ranked": [], "mode": "fast_path_skip"}
        if fast_path
        else global_priority_engine(
            user_id=int(user_id),
            organization_id=int(organization_id),
            limit=20,
        )
    )
    decision_memory = decision_memory_context(user_id=int(user_id), organization_id=int(organization_id))
    pattern_intelligence = build_pattern_intelligence(user_id=int(user_id), organization_id=int(organization_id))
    value_generation_context = run_value_generation_cycle(
        int(user_id),
        int(organization_id),
        command_hint=cmd,
        execution_memory=decision_memory,
        domain_context=domain_ctx,
        identity_context=identity_ctx,
        failure_playbook=(
            pattern_intelligence.get("failure_playbook")
            if isinstance(pattern_intelligence, dict)
            else {}
        ),
        pattern_intelligence=pattern_intelligence,
    )
    limits = _user_limits(int(user_id))
    if int(history_ctx.get("previous_attempts") or 0) >= int(limits.get("max_retry_depth") or 1):
        assist_result = {
            "ok": False,
            "assist_only": True,
            "reason": "max_retry_depth_exceeded",
        }
        return _with_identity_trace({
            "intent": intent,
            "plan": [],
            "result": assist_result,
            "confidence": _zero_confidence(),
            "status": "assist",
            "lifecycle_state": "assist",
            "autonomy_limits": limits,
            "execution_history_context": history_ctx,
            "value_generation_context": value_generation_context,
            "execution_trace_id": execution_trace_id,
            "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)
    plan_steps = build_plan_steps_from_command(
        cmd,
        history_context=history_ctx,
        execution_context=domain_ctx,
        capability_context=capability_ctx,
    )
    plan_steps = adapt_plan_with_intelligence(
        plan_steps,
        pattern_intelligence=pattern_intelligence,
        domain_context=domain_ctx,
        realtime_events=realtime_events,
        decision_memory=decision_memory,
    )
    if fast_path:
        # Latency optimization: skip non-essential deep-reasoning scaffolding on simple commands.
        plan_steps = [
            s
            for s in plan_steps
            if str(s.get("phase") or "") in {"decide", "act"} or str(s.get("step_kind") or "") in {"internal_summarize", "plugin_notify"}
        ] or plan_steps[:2]
        for idx, row in enumerate(plan_steps, start=1):
            row["step_order"] = idx
    plan_steps = apply_style_to_plan(plan_steps, style=str(agent_profile.get("style") or "balanced"))
    if not plan_steps:
        return _with_identity_trace({
            "intent": intent,
            "plan": [],
            "result": {"ok": False, "error": "empty_plan"},
            "confidence": _zero_confidence(),
            "status": "failed",
            "lifecycle_state": "failed",
            "agent_profile": agent_profile,
            "mission_alignment_score": mission_alignment,
            "multi_agent_collaboration": collab,
            "value_generation_context": value_generation_context,
            "execution_trace_id": execution_trace_id,
            "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)
    plan_confidence_score = 0.0
    try:
        p0 = plan_steps[0].get("payload") if isinstance(plan_steps[0].get("payload"), dict) else {}
        plan_confidence_score = float(p0.get("plan_confidence_score") or 0.0)
    except Exception:
        plan_confidence_score = 0.0

    pf = preflight_plan_execution_safety(
        user_id=int(user_id),
        intent=str(intent),
        command=cmd,
        plan_steps=plan_steps,
    )
    preview_steps = list(pf.get("preview_steps") or [])
    mark_pipeline_stage("preflight")

    trust_score = float(calculate_prediction_accuracy(int(user_id), limit=260).get("system_trust_score") or 50.0)
    perf = monitor_system_performance(user_id=int(user_id), organization_id=int(organization_id), hours=24 * 7)
    recent_failure_rate = float(perf.get("failure_rate") or 0.0)
    system_mode = _system_mode()
    limits = _user_limits(int(user_id))
    usage = _current_usage(user_id=int(user_id), organization_id=int(organization_id))
    if int(usage.get("parallel_runs") or 0) >= int(limits.get("max_parallel_runs") or 1):
        assist_result = {
            "ok": False,
            "assist_only": True,
            "reason": "max_parallel_runs_exceeded",
        }
        return _with_identity_trace({
            "intent": intent,
            "plan": _attach_safety_to_plan(plan_steps, preview_steps),
            "result": assist_result,
            "confidence": _zero_confidence(),
            "status": "assist",
            "lifecycle_state": "assist",
            "system_mode": system_mode,
            "autonomy_limits": limits,
            "autonomy_usage": usage,
            "value_generation_context": value_generation_context,
            "execution_trace_id": execution_trace_id,
            "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)
    if int(usage.get("daily_actions") or 0) >= int(limits.get("max_daily_actions") or 1):
        assist_result = {
            "ok": False,
            "assist_only": True,
            "reason": "max_daily_actions_exceeded",
        }
        return _with_identity_trace({
            "intent": intent,
            "plan": _attach_safety_to_plan(plan_steps, preview_steps),
            "result": assist_result,
            "confidence": _zero_confidence(),
            "status": "assist",
            "lifecycle_state": "assist",
            "system_mode": system_mode,
            "autonomy_limits": limits,
            "autonomy_usage": usage,
            "value_generation_context": value_generation_context,
            "execution_trace_id": execution_trace_id,
            "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)
    prev = list(history_ctx.get("previous_outcomes") or [])
    repeated_failure_rate = (
        sum(
            1
            for x in prev
            if str(x.get("final_status") or x.get("status") or "").lower() == "failed"
            or str(x.get("outcome_assessment") or "").lower() == "mismatch"
        )
        / max(1, len(prev))
    ) if prev else 0.0
    gov_decision = compute_autonomy_decision(
        user_id=int(user_id),
        organization_id=int(organization_id),
        domain=str(domain_ctx.get("domain") or "general"),
        system_trust_score=trust_score,
        action_risk_score=float(pf.get("max_risk_score") or 0.0),
        plan_confidence_score=float(plan_confidence_score),
        recent_failure_rate=recent_failure_rate,
        repeated_failure_rate=float(repeated_failure_rate),
        style=str(agent_profile.get("style") or "balanced"),
        active_triggers=list(realtime_events.get("triggers") or []),
        identity_context=identity_ctx,
        mission_importance=float(long_term_alignment),
    )
    circuit_threshold = float((os.getenv("THIRAMAI_CIRCUIT_BREAKER_FAILURE_RATE") or "0.35").strip() or 0.35)
    if recent_failure_rate > circuit_threshold:
        gov_decision = {
            **gov_decision,
            "allow_execute": False,
            "mode": "assist",
            "reason": f"circuit_breaker_open_failure_rate_{recent_failure_rate:.3f}",
        }
    if system_mode == "safe_mode":
        gov_decision = {
            **gov_decision,
            "allow_execute": False,
            "mode": "assist",
            "reason": "system_mode_safe_mode",
        }
    # Hard safety limit: never override governor disallow.

    exec_plan = apply_governor_mode_to_plan(plan_steps, autonomy_decision=gov_decision)
    if not exec_plan and str(gov_decision.get("mode") or "") != "assist":
        gov_decision = {
            **gov_decision,
            "allow_execute": False,
            "mode": "assist",
            "reason": f"{str(gov_decision.get('reason') or '')}; empty_plan_after_governor_constraints",
            "max_execution_depth": 0,
        }
    if str(gov_decision.get("mode") or "") == "semi":
        pf = preflight_plan_execution_safety(
            user_id=int(user_id),
            intent=str(intent),
            command=cmd,
            plan_steps=exec_plan,
        )
        preview_steps = list(pf.get("preview_steps") or [])
    plan_out = _attach_safety_to_plan(exec_plan if exec_plan else plan_steps, preview_steps)
    decision_ctx = _normalize_decision_context(
        intent=intent,
        mission_alignment=mission_alignment,
        plan_confidence_score=plan_confidence_score,
        trust_score=trust_score,
        recent_failure_rate=recent_failure_rate,
        identity_influence=identity_influence,
        long_term_alignment=long_term_alignment,
    )
    roi_hint = float(
        ((global_priority.get("ranked") or [{}])[0] if isinstance(global_priority, dict) and list(global_priority.get("ranked") or []) else {}).get("roi_score")
        or 0.0
    )
    if roi_hint > 1.0:
        roi_hint = roi_hint / 100.0
    memory_hint = float(decision_memory.get("decision_success_rate") or 0.5)
    signal_fusion = _signal_fusion_vector(
        kill_switch_active=kill_switch_on,
        governor_mode=str(gov_decision.get("mode") or ""),
        mission_alignment=float(mission_alignment or 0.0),
        roi_hint=float(roi_hint),
        memory_hint=memory_hint,
    )
    exec_summary = _build_execution_summary(
        reason=str(gov_decision.get("reason") or "governor_evaluated_execution"),
        decision_context=decision_ctx,
        signal_fusion=signal_fusion,
        thinking_profile=thinking,
    )

    if not gov_decision.get("allow_execute"):
        assist_result = {
            "ok": False,
            "assist_only": True,
            "reason": str(gov_decision.get("reason") or "autonomy_governor_assist_mode"),
            "suggestion": "Review plan and confirm manually before execution.",
        }
        return _with_identity_trace({
            "intent": intent,
            "plan": plan_out,
            "result": assist_result,
            "confidence": _zero_confidence(),
            "plan_confidence_score": plan_confidence_score,
            "autonomy_governor_decision": gov_decision,
            "status": "assist",
            "lifecycle_state": lifecycle_from_brain_fields(
                status="assist",
                result=assist_result,
                governor_decision=gov_decision,
            ),
            "execution_history_context": history_ctx,
            "self_generated_goals": self_goals,
            "decision_memory_context": decision_memory,
            "pattern_intelligence": pattern_intelligence,
            "execution_domain_context": domain_ctx,
            "execution_capability_registry": capability_ctx,
            "realtime_event_intelligence": realtime_events,
            "agent_profile": agent_profile,
            "mission_alignment_score": mission_alignment,
            "multi_agent_collaboration": collab,
            "proposed_goals": list(self_goals.get("proposed_goals") or []),
            "goal_confidence": float(self_goals.get("goal_confidence") or 0.0),
            "global_priority": global_priority,
            "self_improvement_backlog": safe_self_improvement_backlog(
                user_id=int(user_id), organization_id=int(organization_id)
            ) if not fast_path else {"ok": True, "tasks": [], "gaps": [], "mode": "fast_path_skip"},
            "thinking_depth_profile": thinking,
            "signal_fusion_vector": signal_fusion,
            "execution_summary": exec_summary,
            "value_generation_context": value_generation_context,
            "execution_trace_id": execution_trace_id,
            "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)

    if not pf.get("allowed"):
        blocked_result = {
            "ok": False,
            "blocked": True,
            "reason": str(pf.get("reason") or "safety_preflight_blocked"),
            "blocked_step_order": pf.get("blocked_step_order"),
            "governance": pf.get("governance"),
            "max_risk_score": pf.get("max_risk_score"),
            "simulation": pf.get("simulation"),
        }
        return _with_identity_trace({
            "intent": intent,
            "plan": plan_out,
            "result": blocked_result,
            "confidence": _zero_confidence(),
            "plan_confidence_score": plan_confidence_score,
            "autonomy_governor_decision": gov_decision,
            "status": "blocked",
            "lifecycle_state": lifecycle_from_brain_fields(
                status="blocked",
                result=blocked_result,
                governor_decision=gov_decision,
            ),
            "agent_profile": agent_profile,
            "mission_alignment_score": mission_alignment,
            "realtime_event_intelligence": realtime_events,
            "multi_agent_collaboration": collab,
            "proposed_goals": list(self_goals.get("proposed_goals") or []),
            "goal_confidence": float(self_goals.get("goal_confidence") or 0.0),
            "global_priority": global_priority,
            "decision_memory_context": decision_memory,
            "pattern_intelligence": pattern_intelligence,
            "self_improvement_backlog": safe_self_improvement_backlog(
                user_id=int(user_id), organization_id=int(organization_id)
            ) if not fast_path else {"ok": True, "tasks": [], "gaps": [], "mode": "fast_path_skip"},
            "thinking_depth_profile": thinking,
            "signal_fusion_vector": signal_fusion,
            "execution_summary": exec_summary,
            "value_generation_context": value_generation_context,
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)

    sim_snap = pf.get("simulation") if isinstance(pf.get("simulation"), dict) else {}
    run = create_action_execution_run(
        user_id=int(user_id),
        organization_id=int(organization_id),
        command=cmd,
        plan_steps=exec_plan,
        preflight_extras={
            "brain_safety_preflight_v1": True,
            "execution_history_context": history_ctx,
            "self_generated_goals": self_goals,
            "decision_memory_context": decision_memory,
            "pattern_intelligence": pattern_intelligence,
            "execution_domain_context": domain_ctx,
            "execution_capability_registry": capability_ctx,
            "realtime_event_intelligence": realtime_events,
            "agent_profile": agent_profile,
            "mission_alignment_score": mission_alignment,
            "identity_influence": identity_influence,
            "long_term_alignment": long_term_alignment,
            "identity_context": identity_ctx,
            "multi_agent_collaboration": {
                "subtasks": collab.get("subtasks"),
                "assignments": collab.get("assignments"),
                "final_synthesis": collab.get("final_synthesis"),
                "consensus_score": float(((collab.get("final_synthesis") or {}) if isinstance(collab.get("final_synthesis"), dict) else {}).get("consensus_score") or 0.0),
                "conflict_resolution": str(((collab.get("final_synthesis") or {}) if isinstance(collab.get("final_synthesis"), dict) else {}).get("conflict_resolution") or ""),
            },
            "thinking_depth_profile": thinking,
            "signal_fusion_vector": signal_fusion,
            "execution_summary": exec_summary,
            "value_generation_context": value_generation_context,
            "autonomy_governor_decision": gov_decision,
            "execution_trace_id": execution_trace_id,
            "preflight_by_order": dict(pf.get("preflight_by_order") or {}),
            "preflight_max_risk_score": int(pf.get("max_risk_score") or 0),
            "preflight_simulation_snapshot": {k: sim_snap.get(k) for k in ("proceed", "success_probability", "skipped", "reason") if k in sim_snap},
        },
    )
    if run is None:
        return _with_identity_trace({
            "intent": intent,
            "plan": plan_out,
            "result": {"ok": False, "error": "run_create_failed"},
            "confidence": _zero_confidence(),
            "plan_confidence_score": plan_confidence_score,
            "autonomy_governor_decision": gov_decision,
            "status": "failed",
            "lifecycle_state": "failed",
            "agent_profile": agent_profile,
            "mission_alignment_score": mission_alignment,
            "multi_agent_collaboration": collab,
            "value_generation_context": value_generation_context,
        }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)

    rid = int(run.get("run_id") or 0)
    activate_execution_context(rid)
    ctx = ActionExecutionContext(
        user_id=int(user_id),
        organization_id=int(organization_id),
        role_name="",
    )
    exec_res = run_persisted_action_plan(run_id=rid, ctx=ctx)
    mark_pipeline_stage("execute_action_plan")
    closure_res = handle_execution_closure(rid)
    mark_pipeline_stage("closure")
    mark_pipeline_stage("retry_learning")
    try:
        assert_pipeline_sequence()
    except PipelineViolationError:
        exec_res = {"ok": False, "error": "pipeline_violation", "original_result": exec_res}
    finally:
        clear_execution_context()
    record_identity_memory(
        user_id=int(user_id),
        organization_id=int(organization_id),
        memory_type="decisions",
        item={
            "command": cmd[:500],
            "intent": intent,
            "mode": gov_decision.get("mode"),
            "mission_alignment": mission_alignment,
            "plan_confidence_score": plan_confidence_score,
            "risk_score": gov_decision.get("risk_score"),
        },
    )
    record_identity_memory(
        user_id=int(user_id),
        organization_id=int(organization_id),
        memory_type="outcomes",
        item={
            "run_id": rid,
            "ok": bool(exec_res.get("ok")),
            "partial": bool(exec_res.get("partial")),
            "confidence": (exec_res.get("confidence") if isinstance(exec_res.get("confidence"), dict) else {}),
            "mission_alignment": mission_alignment,
            "success": bool(exec_res.get("ok") is True),
        },
    )
    conf = exec_res.get("confidence") if isinstance(exec_res.get("confidence"), dict) else _zero_confidence()

    return _with_identity_trace({
        "intent": intent,
        "plan": plan_out,
        "result": exec_res,
        "execution_trace_id": execution_trace_id,
        "timings_ms": {"total_time": round((time.perf_counter() - t0) * 1000.0, 2)},
        "confidence": conf,
        "plan_confidence_score": plan_confidence_score,
        "autonomy_governor_decision": gov_decision,
        "status": _status_from_result(exec_res),
        "lifecycle_state": lifecycle_from_brain_fields(
            status=_status_from_result(exec_res),
            result=exec_res if isinstance(exec_res, dict) else {},
            governor_decision=gov_decision,
        ),
        "execution_history_context": history_ctx,
        "proposed_goals": list(self_goals.get("proposed_goals") or []),
        "goal_confidence": float(self_goals.get("goal_confidence") or 0.0),
        "global_priority": global_priority,
        "decision_memory_context": decision_memory,
        "pattern_intelligence": pattern_intelligence,
        "execution_domain_context": domain_ctx,
        "execution_capability_registry": capability_ctx,
        "realtime_event_intelligence": realtime_events,
        "agent_profile": agent_profile,
        "mission_alignment_score": mission_alignment,
        "identity_influence": identity_influence,
        "long_term_alignment": long_term_alignment,
        "identity_context": identity_ctx,
        "multi_agent_collaboration": collab,
        "self_improvement_backlog": safe_self_improvement_backlog(
            user_id=int(user_id), organization_id=int(organization_id)
        ) if not fast_path else {"ok": True, "tasks": [], "gaps": [], "mode": "fast_path_skip"},
        "thinking_depth_profile": thinking,
        "signal_fusion_vector": signal_fusion,
        "execution_summary": exec_summary,
        "value_generation_context": value_generation_context,
        "closure": {
            "queued": bool((closure_res or {}).get("retry_scheduled")),
            "mode": "brain_execute_immediate_closure",
            "run_id": rid,
            "final_status": str((closure_res or {}).get("final_status") or "unknown"),
            "result": closure_res if isinstance(closure_res, dict) else {},
        },
    }, mission_alignment_score=mission_alignment, identity_influence=identity_influence, long_term_alignment=long_term_alignment, identity_context=identity_ctx)
