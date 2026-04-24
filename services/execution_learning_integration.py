"""
Learning hooks for action execution closure and auto-retry.

Centralizes ``record_outcome`` (``source_type="execution"``), ``record_prediction_vs_actual``,
and ``update_strategy_profiles`` so the system improves after each cycle.
"""

from __future__ import annotations

from typing import Any


def _result_dict_from_stepish(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        r = step.get("result")
        return dict(r) if isinstance(r, dict) else {}
    rj = getattr(step, "result_json", None)
    return dict(rj) if isinstance(rj, dict) else {}


def extract_profit_loss_from_steps(steps: list[Any] | None) -> float:
    """Sum monetary hints from step results (best-effort; defaults to 0)."""
    total = 0.0
    for s in steps or []:
        r = _result_dict_from_stepish(s)
        for key in ("realized_profit", "profit_loss", "realized_pnl", "pnl", "delta", "amount"):
            if key not in r:
                continue
            try:
                total += float(r.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return round(total, 4)


def extract_profit_loss_from_exec_result(exec_res: dict[str, Any] | None) -> float:
    """Aggregate P/L from ``execute_action_plan`` / ``run_persisted_action_plan`` style ``steps``."""
    if not isinstance(exec_res, dict):
        return 0.0
    rows = exec_res.get("steps") if isinstance(exec_res.get("steps"), list) else []
    return extract_profit_loss_from_steps(rows)


def apply_execution_closure_learning(
    *,
    user_id: int,
    organization_id: int,
    run_id: int,
    source_command: str,
    outcome_assessment: str,
    final_status: str,
    success: bool,
    confidence: dict[str, Any],
    steps_for_pnl: list[Any],
) -> dict[str, Any]:
    """
    ``record_outcome`` (execution) + feedback calibration + strategy profile refresh.
    """
    from services.feedback_engine import record_prediction_vs_actual
    from services.learning_engine import record_outcome, update_strategy_profiles

    pnl = extract_profit_loss_from_steps(steps_for_pnl)
    pred_conf = float((confidence or {}).get("score") or 0.5)

    rec = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="execution",
        source_id=int(run_id),
        input_data={
            "run_id": int(run_id),
            "closure_final_status": str(final_status),
            "outcome_assessment": str(outcome_assessment),
            "command_preview": str(source_command or "")[:800],
        },
        outcome={
            "success": bool(success),
            "failure": not bool(success),
            "profit_loss": float(pnl),
            "note": f"execution_closure:{final_status}",
            "confidence": confidence,
            "outcome_assessment": str(outcome_assessment),
        },
    )

    fb: dict[str, Any] = {}
    try:
        fb = record_prediction_vs_actual(
            f"action_run_{int(run_id)}",
            {
                "success": bool(success),
                "profit": max(float(pnl), 0.0) if success else 0.0,
                "confidence": pred_conf,
                "strategy": "execution",
                "source_type": "execution",
            },
            {"success": bool(success), "profit": float(pnl)},
            user_id=int(user_id),
            organization_id=int(organization_id),
        )
    except Exception as exc:  # noqa: BLE001
        fb = {"ok": False, "error": str(exc)[:200]}

    strat: dict[str, Any] = {}
    try:
        strat = update_strategy_profiles(int(user_id))
    except Exception as exc:  # noqa: BLE001
        strat = {"ok": False, "error": str(exc)[:200]}

    return {
        "record_outcome": rec,
        "feedback": fb,
        "strategy_profiles": strat,
        "profit_loss": pnl,
    }


def apply_execution_retry_learning(
    *,
    user_id: int,
    organization_id: int,
    parent_run_id: int,
    child_run_id: int,
    attempt: int,
    plan_step_count: int,
    exec_res: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Audit log + ``record_outcome`` for retry pattern + feedback + strategy profiles.
    """
    from services.feedback_engine import record_prediction_vs_actual
    from services.governance_engine import log_execution
    from services.learning_engine import record_outcome, update_strategy_profiles

    er = exec_res if isinstance(exec_res, dict) else {}
    ok = bool(er.get("ok"))
    pnl = extract_profit_loss_from_exec_result(er)
    pred_conf = float(((er.get("confidence") or {}) if isinstance(er.get("confidence"), dict) else {}).get("score") or 0.5)

    payload = {
        "parent_run_id": int(parent_run_id),
        "child_run_id": int(child_run_id),
        "attempt": int(attempt),
        "plan_step_count": int(plan_step_count),
        "execution_ok": ok,
        "profit_loss": pnl,
    }
    log_execution(
        user_id=int(user_id),
        action_type="execution_auto_retry",
        source="auto_retry_engine",
        payload_json=payload,
        result_json={"steps_n": len(er.get("steps") or []), "stopped": er.get("stopped"), "partial": er.get("partial")},
        status="success" if ok else "failed",
        execution_id=f"retry_{parent_run_id}_{child_run_id}",
        reasoning_summary="Auto-retry execution pattern recorded for learning.",
        why_action_taken=f"parent_run={parent_run_id} child_run={child_run_id} attempt={attempt}",
        data_influenced_json={"organization_id": int(organization_id)},
    )

    rec = record_outcome(
        user_id=int(user_id),
        organization_id=int(organization_id),
        source_type="execution",
        source_id=int(child_run_id),
        input_data={
            "run_id": int(child_run_id),
            "parent_run_id": int(parent_run_id),
            "auto_retry_attempt": int(attempt),
            "pattern": "auto_retry",
        },
        outcome={
            "success": ok,
            "failure": not ok,
            "profit_loss": float(pnl),
            "note": "execution_auto_retry",
            "parent_run_id": int(parent_run_id),
            "attempt": int(attempt),
        },
    )

    fb: dict[str, Any] = {}
    try:
        fb = record_prediction_vs_actual(
            f"action_run_{int(child_run_id)}",
            {
                "success": ok,
                "profit": max(float(pnl), 0.0) if ok else 0.0,
                "confidence": pred_conf,
                "strategy": "execution_retry",
                "source_type": "execution",
            },
            {"success": ok, "profit": float(pnl)},
            user_id=int(user_id),
            organization_id=int(organization_id),
        )
    except Exception as exc:  # noqa: BLE001
        fb = {"ok": False, "error": str(exc)[:200]}

    strat: dict[str, Any] = {}
    try:
        strat = update_strategy_profiles(int(user_id))
    except Exception as exc:  # noqa: BLE001
        strat = {"ok": False, "error": str(exc)[:200]}

    return {
        "record_outcome": rec,
        "feedback": fb,
        "strategy_profiles": strat,
        "profit_loss": pnl,
    }
