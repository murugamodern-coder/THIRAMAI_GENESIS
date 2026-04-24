"""Safe self-expansion engine: detect gaps and generate tools with sandbox-first flow."""

from __future__ import annotations

from typing import Any

from services.autonomy_contract_engine import get_autonomy_state
from services.feedback_engine import calculate_prediction_accuracy
from services.goal_prioritization_engine import prioritize_goals
from services.tool_builder_agent import deploy_tool, generate_tool_code, generate_tool_spec, sandbox_test_tool


def detect_capability_gaps(user_id: int) -> dict[str, Any]:
    accuracy = calculate_prediction_accuracy(int(user_id), limit=220)
    prio = prioritize_goals(int(user_id))
    gaps: list[dict[str, Any]] = []
    if float(accuracy.get("accuracy_pct") or 0) < 62.0:
        gaps.append(
            {
                "gap_type": "prediction_quality",
                "description": "Need helper tool to validate assumptions before execution.",
                "proposed_tool": "pre_execution_validator",
            }
        )
    top = prio.get("top_goal") or {}
    if top and float((top.get("signals") or {}).get("urgency") or 0) >= 0.75:
        gaps.append(
            {
                "gap_type": "execution_speed",
                "description": "Need helper tool for faster repetitive goal-cycle actions.",
                "proposed_tool": "goal_cycle_assistant",
            }
        )
    return {"ok": True, "items": gaps}


def run_self_expansion(user_id: int) -> dict[str, Any]:
    mode = str((get_autonomy_state(int(user_id)).get("mode") or "recommend")).lower()
    gaps = detect_capability_gaps(int(user_id))
    actions: list[dict[str, Any]] = []
    for gap in (gaps.get("items") or [])[:2]:
        spec = generate_tool_spec({"name": gap.get("proposed_tool"), "description": gap.get("description")})
        built = generate_tool_code(spec, int(user_id))
        tid = str(built.get("tool_id") or "")
        tested = sandbox_test_tool(tid, int(user_id))
        deployed = {"ok": False, "skipped": True, "reason": "autonomy mode requires approval"}
        # Safe rule: auto-deploy only in high-autonomy modes and only if test is successful.
        if mode in {"auto_low_risk", "auto_policy"} and bool(tested.get("ok")):
            deployed = deploy_tool(tid, int(user_id))
        actions.append({"gap": gap, "spec": spec, "build": built, "test": tested, "deploy": deployed})
    return {"ok": True, "mode": mode, "gaps": gaps.get("items") or [], "actions": actions}
