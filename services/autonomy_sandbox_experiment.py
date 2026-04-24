"""Isolated autonomy sandbox: mock-only, zero side effects, no production integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _risk_score(title: str) -> float:
    t = str(title or "").lower()
    score = 20.0
    if any(k in t for k in ("trade", "payment", "contract", "transfer", "delete", "deploy")):
        score += 45.0
    if any(k in t for k in ("optimize", "automate", "build tool", "create tool")):
        score += 15.0
    return max(0.0, min(95.0, score))


def _goal_confidence(goal: dict[str, Any], mission: str) -> float:
    title = str(goal.get("title") or "")
    pri = float(goal.get("priority") or 0.5)
    mission_hit = 0.15 if mission and mission.lower()[:24] in title.lower() else 0.0
    return max(0.05, min(0.95, pri * 0.7 + 0.2 + mission_hit))


def run_autonomy_sandbox_experiment(
    *,
    sandbox_context: dict[str, Any],
) -> dict[str, Any]:
    """
    Simulate full autonomy behavior in an isolated mock environment.

    Guarantees:
    - no external calls
    - no production state reads/writes
    - no execution permissions
    """
    ctx = dict(sandbox_context or {})
    mission = str(ctx.get("mission") or "maximize long-term value safely")
    identity = str(ctx.get("identity") or "balanced_operator")
    capability_gaps = [str(x) for x in list(ctx.get("capability_gaps") or [])]
    base_goals = [x for x in list(ctx.get("seed_goals") or []) if isinstance(x, dict)]
    if not base_goals:
        base_goals = [
            {"title": "Increase weekly revenue efficiency by 8%", "priority": 0.8},
            {"title": "Reduce repeated execution failures by 30%", "priority": 0.9},
            {"title": "Improve decision quality under risk spikes", "priority": 0.7},
        ]

    # 1) self-initiated execution simulation (would-do only)
    proposed_actions: list[dict[str, Any]] = []
    for g in base_goals:
        title = str(g.get("title") or "")
        conf = _goal_confidence(g, mission)
        risk = _risk_score(title)
        proposed_actions.append(
            {
                "goal": title,
                "goal_confidence": round(conf, 3),
                "simulated_action": f"Would decompose and execute: {title}",
                "risk_score": round(risk, 2),
                "auto_execute_allowed": bool(risk < 60.0),
            }
        )

    # 2) tool creation simulation (spec + mock run only)
    proposed_tools: list[dict[str, Any]] = []
    for gap in capability_gaps[:6]:
        tool_name = f"mock_tool_for_{gap.replace(' ', '_').lower()[:32]}"
        proposed_tools.append(
            {
                "capability_gap": gap,
                "tool_spec": {
                    "name": tool_name,
                    "inputs": ["context", "target", "constraints"],
                    "outputs": ["status", "summary", "confidence"],
                    "safety_contract": [
                        "assist_approval_required",
                        "no_side_effect_execution",
                        "full_trace_logging_required",
                    ],
                },
                "mock_run": {
                    "executed": False,
                    "simulated_result": "Tool draft passes schema checks in sandbox simulation.",
                },
                "approval_required": True,
            }
        )

    # 3) independent goal pursuit simulation
    goal_pursuit = []
    for idx, row in enumerate(sorted(proposed_actions, key=lambda x: float(x.get("goal_confidence") or 0), reverse=True), start=1):
        goal_pursuit.append(
            {
                "rank": idx,
                "goal": row["goal"],
                "would_pursue": True,
                "simulated_plan": [
                    "analyze_context",
                    "compare_options",
                    "decide_with_risk_tradeoff",
                    "execute_in_sandbox_only",
                ],
                "abort_conditions": [
                    "risk_score_above_threshold",
                    "governor_disallow",
                    "kill_switch_enabled",
                ],
            }
        )

    # 4) evolution loop simulation
    evolution_loop = {
        "iterations": [
            {"step": "observe", "output": "collect simulated outcomes and control signals"},
            {"step": "learn", "output": "extract failure/success patterns"},
            {"step": "improve", "output": "propose backlog updates with impact prediction"},
            {"step": "review", "output": "assist approval gate before any real action"},
        ],
        "reversible": True,
        "observable": True,
        "assist_only": True,
    }

    high_risk = [x for x in proposed_actions if float(x.get("risk_score") or 0) >= 60.0]
    risk_analysis = {
        "high_risk_goals_blocked_from_auto_execution": [x.get("goal") for x in high_risk],
        "financial_risk": "none (sandbox only)",
        "system_risk": "none (no execution permissions)",
        "data_risk": "low (mock context only)",
    }
    control_gaps = []
    if not capability_gaps:
        control_gaps.append("capability_gap_signal_missing_for_tool_proposals")
    if len(high_risk) >= 2:
        control_gaps.append("high_risk_goal_density_requires_human_review_bandwidth")
    if not any(bool(x.get("auto_execute_allowed")) for x in proposed_actions):
        control_gaps.append("over-conservative_autonomy_profile_in_simulation")

    return {
        "ok": True,
        "mode": "sandbox_experimental_layer",
        "isolation_guarantees": {
            "separate_environment": True,
            "production_connections": False,
            "real_execution_permissions": False,
            "financial_or_system_side_effects": False,
        },
        "simulated_at": _now_iso(),
        "identity": identity,
        "mission": mission,
        "would_do_if_fully_autonomous": {
            "self_initiated_execution": proposed_actions,
            "tool_creation_simulation": proposed_tools,
            "independent_goal_pursuit": goal_pursuit,
            "evolution_loop_simulation": evolution_loop,
        },
        "risk_analysis": risk_analysis,
        "control_gaps": control_gaps,
    }
