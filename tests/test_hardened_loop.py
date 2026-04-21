from __future__ import annotations

from typing import Any

import pytest

import thiramai.core.executor as executor_mod
from thiramai.main import JarvisCore


def test_hardened_loop_blocks_unsafe_command_and_reviews_block(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = JarvisCore(goal="harden loop", fixed_goal_only=True)
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "strict")

    plan = {
        "goal": "harden loop",
        "total_steps": 2,
        "steps": [
            {
                "id": 1,
                "type": "audit",
                "description": "safe check",
                "command": "whoami",
                "depends_on": [],
                "risk_level": "low",
                "status": "pending",
                "result_history": [],
            },
            {
                "id": 2,
                "type": "audit",
                "description": "unsafe policy command",
                "command": "git push",
                "depends_on": [1],
                "risk_level": "low",
                "status": "pending",
                "result_history": [],
            },
        ],
    }
    monkeypatch.setattr(engine.planner, "create_plan", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(engine.planner, "decompose", lambda p: list(p.get("steps", [])))

    reviews: list[dict[str, Any]] = []

    def fake_review(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if result.get("status") == "blocked":
            out = {
                "status": "fail",
                "reason": "blocked by policy",
                "fix": "stop_and_request_human",
                "suggested_fix": "stop_and_request_human",
                "failure_type": "blocked_command",
                "confidence": 0.0,
            }
            reviews.append(out)
            return out
        out = {
            "status": "pass",
            "reason": "ok",
            "fix": "",
            "suggested_fix": "",
            "failure_type": "invalid_output",
            "confidence": 0.9,
        }
        reviews.append(out)
        return out

    monkeypatch.setattr(engine.reviewer, "review", fake_review)

    records: list[dict[str, Any]] = []

    def fake_step_record_and_branch(
        cycle_id: int,
        task_id: str,
        task: dict[str, Any],
        result: dict[str, Any],
        review: dict[str, Any],
        learning_snapshot: dict[str, Any],
        cycle_dirty_box: list[bool],
    ) -> None:
        _ = learning_snapshot
        if review.get("status") != "pass":
            cycle_dirty_box[0] = True
            task["status"] = "failed"
        else:
            task["status"] = "success"
        records.append({"task_id": task_id, "task": task, "result": result, "review": review, "cycle_id": cycle_id})

    monkeypatch.setattr(engine, "_step_record_and_branch", fake_step_record_and_branch)

    ok = engine.run_one_cycle()

    assert ok is True
    assert len(records) == 2
    assert records[0]["result"]["status"] == "success"
    assert records[1]["result"]["status"] == "blocked"
    assert records[1]["review"]["failure_type"] == "blocked_command"
    assert records[1]["review"]["suggested_fix"] == "stop_and_request_human"


def test_hardened_loop_emergency_brake_on_human_intervention_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = JarvisCore(goal="harden loop", fixed_goal_only=True)
    monkeypatch.setattr(
        engine.planner,
        "create_plan",
        lambda *_args, **_kwargs: {
            "goal": "harden loop",
            "requires_human_intervention": True,
            "strategy": "manual verification required",
            "total_steps": 0,
            "steps": [],
        },
    )

    ok = engine.run_one_cycle()

    assert ok is False
