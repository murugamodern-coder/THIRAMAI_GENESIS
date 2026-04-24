"""Continuous think-evaluate-act-learn loop engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.autonomy_contract_engine import get_autonomy_state
from services.goal_engine import advance_goal_cycle
from services.goal_prioritization_engine import prioritize_goals
from services.governance_engine import log_execution, validate_action
from services.learning_engine import record_outcome, update_strategy_profiles
from services.self_expansion_engine import run_self_expansion
from services.simulation_engine import choose_best_simulated_path
from services.strategy_generator_engine import generate_and_promote
from services.world_model_engine import persist_world_model


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_continuous_thinking_cycle(user_id: int, organization_id: int) -> dict[str, Any]:
    world = persist_world_model(int(user_id), int(organization_id))
    state = get_autonomy_state(int(user_id))
    mode = str((state.get("mode") or "recommend")).lower()
    ranked = prioritize_goals(int(user_id))
    top = ranked.get("top_goal") or {}
    if not top:
        return {"ok": True, "skipped": True, "reason": "no active goals"}
    goal_id = int(top.get("goal_id") or 0)
    payload = {
        "goal_id": goal_id,
        "priority_score": float(top.get("priority_score") or 0),
        "mode": mode,
        "at": _now_iso(),
    }
    gate = validate_action(
        "continuous_thinking_execute",
        {"user_id": int(user_id), "domain": "automation", "payload": payload},
    )
    if not gate.get("allowed"):
        result = {"ok": False, "blocked": True, "reason": gate.get("reason") or "Governance blocked"}
        log_execution(
            user_id=int(user_id),
            action_type="continuous_thinking_execute",
            source="autonomy",
            payload_json=payload,
            result_json=result,
            status="blocked",
            execution_id=f"ctl_{goal_id}",
            reasoning_summary="Continuous loop action blocked by governance.",
            why_action_taken="Top-priority goal selected but blocked by guardrails.",
            data_influenced_json={"goal": top, "mode": mode},
        )
        return result

    simulation = choose_best_simulated_path(
        int(user_id),
        {"goal_id": goal_id, "expected_profit": float(top.get("priority_score") or 0) * 10000.0, "goal": top},
    )
    chosen = simulation.get("chosen_path") or {}
    if mode == "observe":
        result = {"ok": True, "observed": True, "next_goal_id": goal_id, "mode": mode}
    else:
        # Think-before-act: only execute when simulation indicates reasonable success.
        if float(chosen.get("success_probability") or 0) < 0.35:
            result = {"ok": True, "skipped": True, "reason": "simulation low success probability", "simulation": chosen}
        else:
            result = advance_goal_cycle(goal_id=goal_id, user_id=int(user_id))
    # Safe self-expansion runs after primary action.
    expansion = run_self_expansion(int(user_id))
    strategy = generate_and_promote(int(user_id), int(organization_id))
    out = {
        "ok": True,
        "mode": mode,
        "world_model": world,
        "simulation": simulation,
        "selected_goal": top,
        "goal_action": result,
        "self_expansion": expansion,
        "strategy_generation": strategy,
    }
    log_execution(
        user_id=int(user_id),
        action_type="continuous_thinking_execute",
        source="autonomy",
        payload_json=payload,
        result_json=out,
        status="success",
        execution_id=f"ctl_{goal_id}",
        reasoning_summary="Continuous loop evaluated and executed top goal.",
        why_action_taken="Best priority goal selected from scoring engine.",
        data_influenced_json={"goal_signals": top.get("signals") or {}, "mode": mode},
    )
    record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="continuous_loop",
        source_id=goal_id if goal_id > 0 else None,
        input_data={"top_goal": top, "mode": mode},
        outcome={"success": True, "note": "Continuous thinking cycle executed"},
    )
    update_strategy_profiles(int(user_id))
    return out
