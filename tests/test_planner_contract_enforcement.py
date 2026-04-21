from __future__ import annotations

import pytest

import thiramai.core.planner as planner_mod
from thiramai.core.planner import Planner
from thiramai.schemas.contracts import PlanModel, StepModel


def test_create_plan_schema_violation_triggers_safe_human_intervention(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = Planner()
    monkeypatch.setattr(planner_mod, "call_llm_structured", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("schema invalid")))

    plan = planner.create_plan("stabilize autonomous loop")

    assert plan["requires_human_intervention"] is True
    assert plan["steps"] == []
    assert plan["total_steps"] == 0
    assert "human intervention" in plan["strategy"].lower()


def test_create_plan_success_steps_match_step_model(monkeypatch: pytest.MonkeyPatch) -> None:
    planner = Planner()
    model = PlanModel(
        goal="audit repo",
        total_steps=2,
        steps=[
            StepModel(id=1, task_type="audit", command="pwd", description="Show working directory", depends_on=[]),
            StepModel(id=2, task_type="analysis", command="", description="Analyze outputs", depends_on=[1]),
        ],
    )
    monkeypatch.setattr(planner_mod, "call_llm_structured", lambda *_args, **_kwargs: model)

    plan = planner.create_plan("audit repo")

    assert len(plan["steps"]) == 2
    for step in plan["steps"]:
        # Convert planner's internal step shape back into strict StepModel contract.
        StepModel.model_validate(
            {
                "id": step["id"],
                "task_type": step["type"],
                "command": step["command"],
                "description": step["description"],
                "depends_on": step["depends_on"],
            }
        )
