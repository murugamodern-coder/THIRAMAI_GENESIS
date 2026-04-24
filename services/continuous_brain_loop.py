"""
Periodic brain cycle: reconcile action runs and idle ``brain_execute``.

Does not replace schedulers; intended to be invoked from workers or cron-style hooks.
"""

from __future__ import annotations

import logging
import os
import re
import time
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ActionExecutionRun, ExecutionMemoryEntry
from services.autonomy_contract_engine import get_autonomy_state
from services.autonomy_safety_layer import global_autonomy_halted
from services.brain_execute import brain_execute
from services.decision_intelligence_engine import build_decision_analysis
from services.domain_execution_intelligence import load_domain_execution_context
from services.execution_closure_engine import handle_execution_closure
from services.event_listener_engine import detect_realtime_triggers
from services.goal_prioritization_engine import prioritize_goals
from services.governance_engine import log_execution, validate_action
from services.identity_context_loader import load_master_identity_context
from services.jarvis_goal_engine import get_active_goals_sync
from services.lifecycle_state import lifecycle_from_closure_final_status
from services.proactive_autonomy_engine import global_priority_engine, suggest_next_actions
from services.proactive_autonomy_engine import generate_controlled_self_goals
from services.strategic_goal_planner import build_strategic_goal_plan
from services.action_execution_engine import cancel_action_execution_run
from services.meta_autonomy_engine import self_correction_triggers
from services.p2_intelligence import build_pattern_intelligence, decision_memory_context
from services.realtime_research_engine import run_realtime_research_cycle
from services.result_execution_engine import run_result_execution_cycle
from services.self_learning_engine import run_self_learning_cycle
from services.continuous_intelligence_engine import run_continuous_thinking
from services.intent_generation_engine import run_intent_generation_cycle
from services.intent_execution_engine import run_intent_execution_cycle
from services.autonomous_action_engine import run_autonomous_action_cycle
from services.execution_decision_engine import run_execution_decision_cycle
from services.value_generation_engine import run_value_generation_cycle

_log = logging.getLogger("thiramai.continuous_brain_loop")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _has_running_execution(*, user_id: int, organization_id: int) -> bool:
    fn = _session_factory_or_none()
    if fn is None:
        return False
    with fn() as session:
        n = session.execute(
            select(ActionExecutionRun.id).where(
                ActionExecutionRun.user_id == int(user_id),
                ActionExecutionRun.organization_id == int(organization_id),
                ActionExecutionRun.status == "running",
            ).limit(1)
        ).first()
        return n is not None


def _fetch_run_ids(
    *,
    user_id: int,
    organization_id: int,
    pending_limit: int = 30,
    failed_limit: int = 30,
) -> tuple[list[int], list[int]]:
    fn = _session_factory_or_none()
    if fn is None:
        return [], []
    pending_status = ("planned", "awaiting_confirmation", "running")
    with fn() as session:
        p_rows = session.scalars(
            select(ActionExecutionRun.id)
            .where(
                ActionExecutionRun.user_id == int(user_id),
                ActionExecutionRun.organization_id == int(organization_id),
                ActionExecutionRun.status.in_(pending_status),
            )
            .order_by(ActionExecutionRun.updated_at.desc())
            .limit(int(pending_limit))
        ).all()
        f_rows = session.scalars(
            select(ActionExecutionRun.id)
            .where(
                ActionExecutionRun.user_id == int(user_id),
                ActionExecutionRun.organization_id == int(organization_id),
                ActionExecutionRun.status == "failed",
            )
            .order_by(ActionExecutionRun.updated_at.desc())
            .limit(int(failed_limit))
        ).all()
    return [int(x) for x in p_rows], [int(x) for x in f_rows]


def _running_run_ids(*, user_id: int, organization_id: int, limit: int = 20) -> list[int]:
    fn = _session_factory_or_none()
    if fn is None:
        return []
    with fn() as session:
        rows = session.scalars(
            select(ActionExecutionRun.id)
            .where(
                ActionExecutionRun.user_id == int(user_id),
                ActionExecutionRun.organization_id == int(organization_id),
                ActionExecutionRun.status == "running",
            )
            .order_by(ActionExecutionRun.updated_at.desc())
            .limit(max(1, min(int(limit), 100)))
        ).all()
    return [int(x) for x in rows]


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _extract_expected_profit(action: dict[str, Any]) -> float:
    detail = action.get("detail") if isinstance(action.get("detail"), dict) else {}
    for key in ("expected_profit", "estimated_profit", "profit", "value", "amount"):
        if key in detail:
            return _to_float(detail.get(key), 0.0)
    # fallback: infer a lightweight expected value from ranked priority
    p = max(0.0, min(1.0, _to_float(action.get("priority"), 0.5)))
    return p * 1000.0


def _extract_risk(action: dict[str, Any]) -> float:
    detail = action.get("detail") if isinstance(action.get("detail"), dict) else {}
    rv = detail.get("risk")
    if isinstance(rv, str):
        m = {"low": 0.2, "medium": 0.5, "high": 0.8}
        return m.get(rv.strip().lower(), 0.5)
    if rv is not None:
        r = _to_float(rv, 0.5)
        return r / 100.0 if r > 1.0 else max(0.0, min(1.0, r))
    rs = detail.get("risk_score")
    if rs is not None:
        r2 = _to_float(rs, 50.0)
        return max(0.0, min(1.0, r2 / 100.0))
    return 0.5


def _extract_confidence(action: dict[str, Any]) -> float:
    detail = action.get("detail") if isinstance(action.get("detail"), dict) else {}
    cv = detail.get("confidence")
    if cv is not None:
        c = _to_float(cv, 0.0)
        return c / 100.0 if c > 1.0 else max(0.0, min(1.0, c))
    return max(0.0, min(1.0, _to_float(action.get("priority"), 0.5)))


def _score_idle_options(
    actions: list[dict[str, Any]],
    *,
    domain_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # score = expected_profit (up) + confidence (up) - risk (down)
    rows: list[dict[str, Any]] = []
    if not actions:
        return rows
    dc = domain_context if isinstance(domain_context, dict) else {}
    risk_models = list(dc.get("risk_models") or [])
    pricing_patterns = list(dc.get("pricing_patterns") or [])
    conservative = any("conservative" in str(x).lower() for x in risk_models)
    profit_weight = 0.50 + min(0.10, 0.02 * len(pricing_patterns))
    confidence_weight = 0.35
    risk_weight = 0.15 + (0.10 if conservative else 0.0)
    profits = [_extract_expected_profit(a) for a in actions]
    pmax = max(max(profits), 1.0)
    for idx, a in enumerate(actions):
        exp_profit = profits[idx]
        risk = _extract_risk(a)
        conf = _extract_confidence(a)
        profit_norm = max(0.0, min(1.0, exp_profit / pmax))
        score = (profit_weight * profit_norm) + (confidence_weight * conf) - (risk_weight * risk)
        rows.append(
            {
                "action": a,
                "expected_profit": round(exp_profit, 2),
                "risk": round(risk, 4),
                "confidence": round(conf, 4),
                "domain": str(dc.get("domain") or "business"),
                "score": round(score, 6),
            }
        )
    rows.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return rows


def _tokenize(s: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9_]+", (s or "").lower()) if len(x) >= 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    if union <= 0:
        return 0.0
    return float(inter / union)


def _fetch_recent_execution_memory(
    *,
    user_id: int,
    organization_id: int,
    limit: int = 120,
) -> list[dict[str, Any]]:
    fn = _session_factory_or_none()
    if fn is None:
        return []
    lim = max(1, min(int(limit), 300))
    with fn() as session:
        rows = (
            session.execute(
                select(ExecutionMemoryEntry)
                .where(
                    ExecutionMemoryEntry.user_id == int(user_id),
                    ExecutionMemoryEntry.organization_id == int(organization_id),
                )
                .order_by(ExecutionMemoryEntry.created_at.desc(), ExecutionMemoryEntry.id.desc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        d = r.detail_json if isinstance(r.detail_json, dict) else {}
        out.append(
            {
                "step_kind": str(r.step_kind or ""),
                "success": bool(r.success),
                "summary": str(r.summary or ""),
                "detail_json": d,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def _memory_patterns(memory_rows: list[dict[str, Any]], *, top_n: int = 10) -> dict[str, Any]:
    failures = [m for m in memory_rows if not bool(m.get("success"))]
    successes = [m for m in memory_rows if bool(m.get("success"))]
    return {
        "recent_execution_memory_entries": memory_rows[: max(1, min(int(top_n), 30))],
        "recent_failure_patterns": failures[: max(1, min(int(top_n), 30))],
        "recent_success_patterns": successes[: max(1, min(int(top_n), 30))],
    }


def _apply_memory_bias(
    scored_rows: list[dict[str, Any]],
    *,
    memory_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not scored_rows or not memory_rows:
        return scored_rows
    out: list[dict[str, Any]] = []
    for row in scored_rows:
        act = row.get("action") if isinstance(row.get("action"), dict) else {}
        title = str(act.get("title") or "")
        kind = str(act.get("kind") or "")
        action_tokens = _tokenize(f"{title} {kind}")
        fail_pen = 0.0
        succ_boost = 0.0
        matched_failures: list[str] = []
        matched_successes: list[str] = []
        for mem in memory_rows[:80]:
            mem_text = f"{mem.get('step_kind') or ''} {mem.get('summary') or ''} {((mem.get('detail_json') or {}).get('error_class') or '')}"
            sim = _jaccard(action_tokens, _tokenize(mem_text))
            if sim < 0.08:
                continue
            if bool(mem.get("success")):
                succ_boost += min(0.12, sim * 0.20)
                if len(matched_successes) < 3:
                    matched_successes.append(str(mem.get("summary") or mem.get("step_kind") or "")[:140])
            else:
                fail_pen += min(0.20, sim * 0.28)
                if len(matched_failures) < 3:
                    matched_failures.append(str(mem.get("summary") or mem.get("step_kind") or "")[:140])
        adjusted = float(row.get("score") or 0.0) + float(succ_boost) - float(fail_pen)
        out.append(
            {
                **row,
                "memory_failure_penalty": round(fail_pen, 6),
                "memory_success_boost": round(succ_boost, 6),
                "memory_adjusted_score": round(adjusted, 6),
                "memory_match_failures": matched_failures,
                "memory_match_successes": matched_successes,
            }
        )
    out.sort(key=lambda x: float(x.get("memory_adjusted_score") or x.get("score") or 0.0), reverse=True)
    return out


def _pick_idle_action_with_decision_intelligence(
    *,
    user_id: int,
    organization_id: int,
    actions: list[dict[str, Any]],
    domain_context: dict[str, Any] | None = None,
    agent_profile: dict[str, Any] | None = None,
    identity_context: dict[str, Any] | None = None,
    recent_memory_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dc = domain_context if isinstance(domain_context, dict) else {}
    recent_memory = (
        [x for x in list(recent_memory_rows or []) if isinstance(x, dict)]
        if isinstance(recent_memory_rows, list)
        else _fetch_recent_execution_memory(
            user_id=int(user_id),
            organization_id=int(organization_id),
            limit=120,
        )
    )
    memory_hints = _memory_patterns(recent_memory, top_n=12)
    scored = _apply_memory_bias(
        _score_idle_options(actions, domain_context=dc),
        memory_rows=recent_memory,
    )
    if not scored:
        return {
            "selected": None,
            "scored": [],
            "decision_pack": None,
            "selected_confidence": 0.0,
            "memory_hints": memory_hints,
            "domain_context": dc,
        }

    top3 = scored[:3]
    options_text = []
    for i, row in enumerate(top3, start=1):
        t = str((row.get("action") or {}).get("title") or "").strip()[:220]
        options_text.append(
            f"Option {i}: {t} | expected_profit={row['expected_profit']}, risk={row['risk']}, confidence={row['confidence']}, score={row.get('memory_adjusted_score', row['score'])}, memory_fail_penalty={row.get('memory_failure_penalty', 0)}, memory_success_boost={row.get('memory_success_boost', 0)}"
        )
    decision_brief = (
        "Choose best idle action using weighted scoring (profit/risk/confidence).\n"
        + "\n".join(options_text)
    )
    decision_pack = build_decision_analysis(
        user_id=int(user_id),
        title="Idle brain action selection",
        decision_brief=decision_brief,
        context={
            "organization_id": int(organization_id),
            "expected_profit_baseline": float(top3[0]["expected_profit"] or 0.0),
            "candidate_scores": [
                {
                    "title": str((r.get("action") or {}).get("title") or "")[:220],
                    "score": r.get("score"),
                    "memory_adjusted_score": r.get("memory_adjusted_score"),
                    "expected_profit": r.get("expected_profit"),
                    "risk": r.get("risk"),
                    "confidence": r.get("confidence"),
                    "memory_failure_penalty": r.get("memory_failure_penalty"),
                    "memory_success_boost": r.get("memory_success_boost"),
                    "memory_match_failures": r.get("memory_match_failures"),
                    "memory_match_successes": r.get("memory_match_successes"),
                }
                for r in top3
            ],
            "memory_hints": memory_hints,
            "domain_context": dc,
            "agent_identity": {
                **dict(agent_profile or {}),
                "master_identity": dict(identity_context or {}),
            },
        },
    )
    primary = str(((decision_pack.get("recommendation") or {}).get("primary_option") or "B")).upper()[:1]
    # A/B/C mapping over ranked list: A=top, B=middle, C=safest(lowest-risk)
    if primary == "A":
        selected = top3[0]
    elif primary == "B":
        selected = top3[min(1, len(top3) - 1)]
    else:
        selected = sorted(top3, key=lambda x: float(x.get("risk") or 1.0))[0]
    return {
        "selected": selected,
        "selected_confidence": float(selected.get("confidence") or 0.0),
        "selected_primary_option": primary,
        "scored": scored,
        "decision_pack": decision_pack,
        "memory_hints": memory_hints,
        "domain_context": dc,
    }


def run_brain_cycle(user_id: int, organization_id: int) -> dict[str, Any]:
    """
    One autonomy-scoped cycle:

    1. Autonomy mode (``observe`` treated as disabled).
    2. Pending / failed action runs → ``auto_retry_execution`` then ``handle_execution_closure``.
    3. Active Jarvis goals captured for summary / idle task selection.
    4. If no ``running`` execution for this tenant → proactive + goal hint → ``brain_execute``.
    5. Audit log for the cycle.
    """
    uid = int(user_id)
    oid = int(organization_id)
    t_cycle0 = time.perf_counter()
    execution_trace_id = f"cbc-{uid}-{oid}-{uuid4()}"
    t_decision_ms = 0.0
    t_execution_ms = 0.0
    out: dict[str, Any] = {
        "ok": True,
        "at": _now_iso(),
        "user_id": uid,
        "organization_id": oid,
        "skipped": False,
        "reason": "",
        "autonomy_mode": "",
        "pending_run_ids": [],
        "failed_run_ids": [],
        "active_goals": [],
        "execution_work": [],
        "had_running_execution": False,
        "idle_brain": None,
        "strategic_plan": None,
        "realtime_events": None,
        "lifecycle_state": "running",
        "self_goal_generation": None,
        "global_priority": None,
        "self_triggered_execution": None,
        "internal_thinking_cycle": None,
        "identity_context": None,
        "value_generation": None,
        "realtime_research": None,
        "self_learning": None,
        "continuous_thinking": None,
        "generated_intents": None,
        "execution_decision": None,
        "execution_trace_id": execution_trace_id,
        "timings_ms": {"decision_time": 0.0, "execution_time": 0.0, "total_cycle_time": 0.0},
        "cache_hits": {"realtime_research": False, "value_generation_inputs": False, "trigger_detection": False},
    }
    identity_ctx = load_master_identity_context()
    out["identity_context"] = identity_ctx

    if global_autonomy_halted():
        out["ok"] = False
        out["skipped"] = True
        out["reason"] = "global_autonomy_halt"
        out["lifecycle_state"] = "blocked"
        _log.warning("continuous_brain_cycle skipped: global autonomy halt user_id=%s", uid)
        return out

    state = get_autonomy_state(uid)
    mode = str((state.get("mode") or "recommend")).lower()
    out["autonomy_mode"] = mode
    if mode == "observe":
        out["skipped"] = True
        out["reason"] = "autonomy_mode_observe"
        out["lifecycle_state"] = "assist"
        _log.info("continuous_brain_cycle skipped: observe mode user_id=%s", uid)
        return out

    gate = validate_action(
        "continuous_brain_cycle",
        {"user_id": uid, "domain": "automation", "payload": {"organization_id": oid, "mode": mode}},
    )
    if not gate.get("allowed"):
        out["ok"] = False
        out["skipped"] = True
        out["reason"] = str(gate.get("reason") or "governance_blocked")
        out["lifecycle_state"] = "blocked"
        return out

    cycle_cache: dict[str, Any] = {}
    events = detect_realtime_triggers(user_id=uid, organization_id=oid)
    cycle_cache["trigger_detection"] = events
    out["cache_hits"]["trigger_detection"] = True
    out["realtime_events"] = events
    triggers = list(events.get("triggers") or [])
    if any(str(t.get("type") or "") == "risk_spike" for t in triggers):
        interrupted: list[dict[str, Any]] = []
        for rid in _running_run_ids(user_id=uid, organization_id=oid, limit=12):
            res = cancel_action_execution_run(run_id=int(rid), user_id=uid)
            interrupted.append({"run_id": int(rid), "cancelled": bool(res is not None)})
        out["interruptions"] = interrupted
        out["strategy_re_evaluation"] = build_strategic_goal_plan(
            user_id=uid,
            organization_id=oid,
            max_goals=24,
        )

    pending_ids, failed_ids = _fetch_run_ids(user_id=uid, organization_id=oid)
    out["pending_run_ids"] = list(pending_ids)
    out["failed_run_ids"] = list(failed_ids)

    goals = get_active_goals_sync(user_id=uid, limit=24)
    out["active_goals"] = [
        {"id": int(g.get("id") or 0), "description": str(g.get("description") or "")[:240], "status": str(g.get("status") or "")}
        for g in goals
        if isinstance(g, dict) and int(g.get("id") or 0) > 0
    ]
    out["strategic_plan"] = build_strategic_goal_plan(
        user_id=uid,
        organization_id=oid,
        max_goals=24,
    )
    out["self_goal_generation"] = generate_controlled_self_goals(
        user_id=uid,
        organization_id=oid,
        limit=8,
    )
    out["global_priority"] = global_priority_engine(
        user_id=uid,
        organization_id=oid,
        limit=20,
    )
    out["realtime_research"] = run_realtime_research_cycle(uid, oid)
    cycle_cache["realtime_research"] = out["realtime_research"]
    out["cache_hits"]["realtime_research"] = True
    decision_mem = decision_memory_context(user_id=uid, organization_id=oid)
    pattern_intel = build_pattern_intelligence(user_id=uid, organization_id=oid)
    recent_exec_rows = _fetch_recent_execution_memory(user_id=uid, organization_id=oid, limit=80)
    recent_exec = {"recent_execution_memory_entries": recent_exec_rows}
    cycle_cache["value_generation_inputs"] = {
        "decision_memory": decision_mem,
        "pattern_intelligence": pattern_intel,
        "recent_execution": recent_exec,
    }
    out["cache_hits"]["value_generation_inputs"] = True
    out["value_generation"] = run_value_generation_cycle(
        uid,
        oid,
        command_hint="continuous_brain_loop_cycle",
        execution_memory={**decision_mem, **recent_exec},
        domain_context={
            "domain": "automation",
            "source": "continuous_brain_loop",
            "realtime_research": out.get("realtime_research"),
        },
        identity_context=identity_ctx,
        failure_playbook=(pattern_intel.get("failure_playbook") if isinstance(pattern_intel, dict) else {}),
        pattern_intelligence=pattern_intel,
    )
    result_execution_candidates = run_result_execution_cycle(
        uid,
        oid,
        value_generation=out.get("value_generation") if isinstance(out.get("value_generation"), dict) else None,
        max_actions=2,
    )
    out["self_learning"] = run_self_learning_cycle(
        uid,
        oid,
        realtime_research=out.get("realtime_research") if isinstance(out.get("realtime_research"), dict) else None,
        value_generation=out.get("value_generation") if isinstance(out.get("value_generation"), dict) else None,
        result_execution=result_execution_candidates if isinstance(result_execution_candidates, dict) else None,
    )
    out["generated_intents"] = run_intent_generation_cycle(
        realtime_research=out.get("realtime_research") if isinstance(out.get("realtime_research"), dict) else None,
        value_generation=out.get("value_generation") if isinstance(out.get("value_generation"), dict) else None,
        self_learning=out.get("self_learning") if isinstance(out.get("self_learning"), dict) else None,
        result_execution=result_execution_candidates if isinstance(result_execution_candidates, dict) else None,
        identity_context=identity_ctx,
    )
    intent_execution_candidates = run_intent_execution_cycle(
        uid,
        oid,
        generated_intents=[x for x in list(out.get("generated_intents") or []) if isinstance(x, dict)],
        identity_context=identity_ctx,
        max_intents_per_cycle=1,
    )
    out["continuous_thinking"] = run_continuous_thinking(
        uid,
        oid,
        realtime_research=out.get("realtime_research") if isinstance(out.get("realtime_research"), dict) else None,
        value_generation=out.get("value_generation") if isinstance(out.get("value_generation"), dict) else None,
        result_execution=result_execution_candidates if isinstance(result_execution_candidates, dict) else None,
        identity_context=identity_ctx,
    )
    autonomous_action_candidates = run_autonomous_action_cycle(
        uid,
        oid,
        continuous_thinking=out.get("continuous_thinking") if isinstance(out.get("continuous_thinking"), dict) else None,
        generated_intents=[x for x in list(out.get("generated_intents") or []) if isinstance(x, dict)],
        value_generation=out.get("value_generation") if isinstance(out.get("value_generation"), dict) else None,
        realtime_research=out.get("realtime_research") if isinstance(out.get("realtime_research"), dict) else None,
        identity_context=identity_ctx,
        max_autonomous_actions_per_cycle=1,
    )
    t_decision0 = time.perf_counter()
    out["execution_decision"] = run_execution_decision_cycle(
        uid,
        oid,
        intent_execution=intent_execution_candidates if isinstance(intent_execution_candidates, dict) else None,
        autonomous_actions=autonomous_action_candidates if isinstance(autonomous_action_candidates, dict) else None,
        value_execution=result_execution_candidates if isinstance(result_execution_candidates, dict) else None,
        max_actions_per_cycle=1,
        execution_trace_id=execution_trace_id,
    )
    t_decision_ms = (time.perf_counter() - t_decision0) * 1000.0
    t_execution_ms = float(((out.get("execution_decision") or {}).get("timings_ms") or {}).get("execution_time", 0.0))
    out["internal_thinking_cycle"] = {
        "decision_review": build_decision_analysis(
            user_id=uid,
            title="Internal thinking cycle",
            decision_brief="Evaluate alternatives and improve strategic posture without direct execution.",
            context={
                "organization_id": oid,
                "self_goals": out.get("self_goal_generation"),
                "global_priority": out.get("global_priority"),
                "self_correction_triggers": self_correction_triggers(user_id=uid, organization_id=oid),
                "agent_identity": {"master_identity": identity_ctx},
            },
        ),
        "simulated_alternatives": list((out.get("global_priority") or {}).get("ranked") or [])[:3],
    }

    seen: set[int] = set()
    ordered: list[int] = []
    for rid in pending_ids + failed_ids:
        if rid in seen:
            continue
        seen.add(rid)
        ordered.append(rid)

    for rid in ordered:
        cl = handle_execution_closure(int(rid))
        lifecycle_state = lifecycle_from_closure_final_status(
            str((cl or {}).get("final_status") or "")
            if isinstance(cl, dict)
            else ""
        )
        out["execution_work"].append(
            {"run_id": int(rid), "closure": cl, "lifecycle_state": lifecycle_state}
        )

    out["had_running_execution"] = _has_running_execution(user_id=uid, organization_id=oid)

    if not out["had_running_execution"]:
        sug = suggest_next_actions(uid, oid, limit=8)
        actions = list(sug.get("actions") or [])
        strategic_short = list(((out.get("strategic_plan") or {}).get("short_term") or []))
        for s in strategic_short[:6]:
            if not isinstance(s, dict):
                continue
            actions.append(
                {
                    "kind": "strategic_short_term",
                    "title": str(s.get("action") or "")[:300],
                    "priority": float(s.get("priority_0_1") or 0.5),
                    "detail": s,
                }
            )
        actions.sort(key=lambda x: float(x.get("priority") or 0.0), reverse=True)
        domain_ctx = load_domain_execution_context(
            user_id=uid,
            organization_id=oid,
            command="; ".join(str(a.get("title") or "") for a in actions[:6]),
            context={"source": "continuous_brain_loop_idle"},
        )
        title = ""
        if actions:
            decision_pick = _pick_idle_action_with_decision_intelligence(
                user_id=uid,
                organization_id=oid,
                actions=actions,
                domain_context=domain_ctx,
                agent_profile=((out.get("strategic_plan") or {}).get("agent_profile") or {}),
                identity_context=identity_ctx,
                recent_memory_rows=recent_exec_rows,
            )
            out["idle_decision"] = {
                "selected_primary_option": decision_pick.get("selected_primary_option"),
                "selected_confidence": decision_pick.get("selected_confidence"),
                "memory_hints": decision_pick.get("memory_hints"),
                "domain_context": decision_pick.get("domain_context"),
                "top_scored": [
                    {
                        "title": str(((r.get("action") or {}).get("title") or ""))[:220],
                        "score": r.get("score"),
                        "memory_adjusted_score": r.get("memory_adjusted_score"),
                        "expected_profit": r.get("expected_profit"),
                        "risk": r.get("risk"),
                        "confidence": r.get("confidence"),
                        "memory_failure_penalty": r.get("memory_failure_penalty"),
                        "memory_success_boost": r.get("memory_success_boost"),
                    }
                    for r in list(decision_pick.get("scored") or [])[:3]
                ],
                "recommendation": ((decision_pick.get("decision_pack") or {}).get("recommendation") or {}),
            }
            selected = decision_pick.get("selected") if isinstance(decision_pick.get("selected"), dict) else {}
            title = str((selected.get("action") or {}).get("title") or "").strip()
            conf_threshold = 0.60
            try:
                conf_threshold = max(
                    0.0,
                    min(1.0, float((os.getenv("THIRAMAI_IDLE_EXECUTION_CONFIDENCE_THRESHOLD") or "0.60").strip())),
                )
            except Exception:
                conf_threshold = 0.60
            if float(decision_pick.get("selected_confidence") or 0.0) < conf_threshold:
                out["idle_brain"] = {
                    "skipped": True,
                    "reason": "idle_confidence_below_threshold",
                    "selected_confidence": float(decision_pick.get("selected_confidence") or 0.0),
                    "confidence_threshold": conf_threshold,
                }
                title = ""
        if not title:
            sg = out.get("self_goal_generation") if isinstance(out.get("self_goal_generation"), dict) else {}
            proposed = [x for x in list(sg.get("proposed_goals") or []) if isinstance(x, dict)]
            safe_candidates = [
                x
                for x in proposed
                if bool(x.get("can_auto_execute"))
                and not bool(x.get("high_risk_goal"))
            ]
            if safe_candidates:
                title = str(safe_candidates[0].get("title") or "").strip()[:800]
        if not title:
            ranked = prioritize_goals(uid)
            top = ranked.get("top_goal") or {}
            title = str(top.get("description") or "").strip()[:800]
        if not title and out["active_goals"]:
            title = str(out["active_goals"][0].get("description") or "").strip()[:800]
        if not title:
            title = "Review workspace priorities and confirm the next highest-impact action."

        high_opp = any(str(t.get("type") or "") == "opportunity_spike" for t in triggers if isinstance(t, dict))
        gaps = self_correction_triggers(user_id=uid, organization_id=oid)
        inefficiency = any(str(t.get("trigger") or "") == "repeated_inefficiency" for t in list(gaps.get("self_correction_triggers") or []))
        detected_gap = any(str(t.get("trigger") or "") == "failure_pattern_detected" for t in list(gaps.get("self_correction_triggers") or []))
        self_triggered = bool(high_opp or inefficiency or detected_gap)
        out["self_triggered_execution"] = {
            "enabled": self_triggered,
            "reasons": {
                "high_opportunity": high_opp,
                "repeated_inefficiency": inefficiency,
                "detected_gap": detected_gap,
            },
        }

        brain_gate = validate_action(
            "continuous_brain_idle_execute",
            {"user_id": uid, "domain": "automation", "payload": {"organization_id": oid, "command_preview": title[:400]}},
        )
        if self_triggered and brain_gate.get("allowed") and not (isinstance(out.get("idle_brain"), dict) and out["idle_brain"].get("skipped")):
            out["idle_brain"] = brain_execute(title, uid, oid)
        elif not brain_gate.get("allowed"):
            out["idle_brain"] = {"skipped": True, "reason": str(brain_gate.get("reason") or "governance_blocked")}
        else:
            out["idle_brain"] = {"skipped": True, "reason": "self_trigger_not_met"}

    summary = {
        "mode": mode,
        "runs_touched": len(ordered),
        "pending_n": len(pending_ids),
        "failed_n": len(failed_ids),
        "goals_n": len(out["active_goals"]),
        "had_running": out["had_running_execution"],
        "idle_fired": bool(out.get("idle_brain")),
        "strategic_short_actions": len(list(((out.get("strategic_plan") or {}).get("short_term") or []))),
        "realtime_trigger_count": len(list((out.get("realtime_events") or {}).get("triggers") or [])),
    }
    out["summary"] = summary
    out["lifecycle_state"] = "completed"
    out["timings_ms"] = {
        "decision_time": round(float(t_decision_ms), 2),
        "execution_time": round(float(t_execution_ms), 2),
        "total_cycle_time": round((time.perf_counter() - t_cycle0) * 1000.0, 2),
    }

    idle_brain = out.get("idle_brain")
    audit_result: dict[str, Any] = {
        "ok": out.get("ok"),
        "skipped": out.get("skipped"),
        "reason": out.get("reason"),
        "autonomy_mode": mode,
        "summary": summary,
        "runs_touched": len(ordered),
        "idle_brain_status": idle_brain.get("status") if isinstance(idle_brain, dict) else None,
        "idle_intent": idle_brain.get("intent") if isinstance(idle_brain, dict) else None,
    }

    log_execution(
        user_id=uid,
        action_type="continuous_brain_cycle",
        source="continuous_brain_loop",
        payload_json={"organization_id": oid, "summary": summary, "run_ids": ordered[:40]},
        result_json=audit_result,
        status="success" if out.get("ok") else "failed",
        execution_id=f"cbc_{uid}_{oid}",
        reasoning_summary="Continuous brain cycle: runs reconciled / idle brain evaluated.",
        why_action_taken="Autonomous loop tick for tenant.",
        data_influenced_json={"organization_id": oid, "runs": ordered[:40]},
    )

    _log.info(
        "continuous_brain_cycle user_id=%s org_id=%s trace=%s runs=%s goals=%s idle=%s total_ms=%.2f",
        uid,
        oid,
        execution_trace_id,
        len(ordered),
        len(out["active_goals"]),
        bool(out.get("idle_brain")),
        float(out["timings_ms"]["total_cycle_time"]),
    )
    return out
