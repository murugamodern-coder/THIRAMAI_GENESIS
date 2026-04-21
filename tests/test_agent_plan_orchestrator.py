"""Agentic orchestrator — plan normalization and approve flow (no live Groq)."""

from __future__ import annotations

import services.orchestrator as orch
from services.orchestrator import approve_and_advance, create_plan_from_command


def test_fallback_plan_then_approve(monkeypatch: object) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    def _noop_execute(rt: orch.AgentPlanRuntime, step_index: int) -> tuple[bool, dict]:
        return True, {"ok": True, "mode": "stub"}

    monkeypatch.setattr(orch, "_execute_step", _noop_execute)

    out = create_plan_from_command(
        "Smoke test command",
        user_id=101,
        organization_id=1,
        os_key="stock",
    )
    assert out.get("ok") is True
    assert out.get("requires_approval") is True
    tid = out["task_id"]

    step1 = approve_and_advance(tid, user_id=101, signal="success")
    assert step1.get("ok") is True
    steps = step1.get("steps") or []
    assert steps and steps[0].get("status") == "completed"
