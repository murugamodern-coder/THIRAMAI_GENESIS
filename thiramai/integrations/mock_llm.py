"""
Deterministic LLM stubs for simulation mode and dry-run text responses.
Enables tests and local runs without OPENAI_API_KEY.
"""

from __future__ import annotations

import json
import re
from typing import Any


def _extract_goal(prompt: str) -> str:
    m = re.search(r"Goal:\s*(.+?)(?:\n|$)", prompt, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:500] or "thiramai-mock-goal"
    return "thiramai-mock-goal"


def mock_llm(prompt: str) -> str:
    """
    Return predictable JSON or text based on prompt shape.
    Used when THIRAMAI_MODE (effective) is simulation.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return '{"status":"fail","reason":"empty prompt","fix":""}'

    p = prompt.lower()

    if "consensus evaluator" in p:
        return json.dumps({"selected_model": "gpt-4o-mini", "justification": "mock deterministic selection"})

    if "autonomous qa reviewer" in p:
        det = "pass" if "deterministic check outcome: pass" in p else "pass"
        return json.dumps({"status": det, "reason": "mock_llm simulation", "fix": ""})

    if "replanning engine" in p:
        goal = _extract_goal(prompt)
        plan = _mock_plan_dict(goal)
        plan["strategy"] = "mock replan strategy"
        return json.dumps(plan)

    if "goal-driven autonomous planner" in p:
        goal = _extract_goal(prompt)
        return json.dumps(_mock_plan_dict(goal))

    if "sovereign autonomous planner" in p and "goals" in p:
        return json.dumps(
            {
                "goals": [
                    {
                        "id": "g_mock_1",
                        "title": "Mock sovereign objective",
                        "description": "Simulation stub goal for testing.",
                        "priority_score": 58.0,
                        "resource_weight": 4.0,
                    }
                ]
            }
        )

    if "create a concise json spec for a safe autonomous helper agent" in p:
        return json.dumps(
            {
                "summary": "Mock generated helper (simulation)",
                "execute_steps": [
                    "Validate task payload fields.",
                    "Summarize findings without shell execution.",
                    "Return structured result for reviewer.",
                ],
            }
        )

    if "analyze the autonomous run output" in p:
        return (
            "Mock analysis: no failures detected in simulation. "
            "Recommend keeping THIRAMAI_MODE=simulation for CI."
        )

    if "self-heal" in p or "patch" in p and "json" in p:
        return json.dumps({"action": "noop", "reason": "mock self-heal"})

    return json.dumps(
        {
            "note": "mock_llm default",
            "echo_prefix": hash(prompt) % 10000,
            "goal_hint": _extract_goal(prompt)[:120],
        }
    )


def _mock_plan_dict(goal: str) -> dict[str, Any]:
    # Use python (allowlisted) so tests pass on Windows where `echo` is not a standalone executable.
    return {
        "goal": goal,
        "strategy": "mock incremental diagnostics",
        "confidence": 0.88,
        "steps": [
            {
                "id": 1,
                "type": "audit",
                "description": "Simulation sanity check (python print)",
                "command": "python -c \"print('THIRAMAI_SIMULATION')\"",
                "success_criteria": "output contains THIRAMAI_SIMULATION",
                "retry_limit": 1,
            }
        ],
    }


def dry_run_llm_response(prompt: str) -> str:
    """Structured stubs when no LLM and no live API (dry-run)."""
    p = prompt.lower()
    if "autonomous qa reviewer" in p:
        return json.dumps({"status": "pass", "reason": "dry-run bypass", "fix": ""})
    if "replanning engine" in p or "goal-driven autonomous planner" in p:
        g = _extract_goal(prompt)
        return json.dumps(
            {
                "goal": g,
                "strategy": "dry-run no-op",
                "confidence": 1.0,
                "steps": [
                    {
                        "id": 1,
                        "type": "audit",
                        "description": "Dry-run marker (executor skipped)",
                        "command": "python -c \"print('THIRAMAI_DRY_RUN')\"",
                        "success_criteria": "output contains THIRAMAI_DRY_RUN",
                        "retry_limit": 0,
                    }
                ],
            }
        )
    if "sovereign autonomous planner" in p and "goals" in p:
        return json.dumps({"goals": []})
    if "analyze the autonomous run output" in p:
        return "dry-run analysis: LLM and execution disabled."
    if "consensus evaluator" in p:
        return json.dumps({"selected_model": "gpt-4o-mini", "justification": "dry-run"})
    return json.dumps({"status": "ok", "mode": "dry-run", "prompt_hash": hash(prompt) % 100000})
