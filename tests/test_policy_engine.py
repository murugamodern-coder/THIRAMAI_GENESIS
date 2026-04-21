from __future__ import annotations

from thiramai.policy.engine import PolicyEngine
from thiramai.policy.models import ExecutionContext


def _ctx(*, risk_level: str = "low") -> ExecutionContext:
    return ExecutionContext(
        tenant_id=101,
        task_type="audit",
        risk_level=risk_level,
        capabilities=["read_fs"],
    )


def test_policy_engine_allows_safe_commands() -> None:
    engine = PolicyEngine(allow_high_risk=False)

    allow_ls = engine.evaluate(["ls"], _ctx())
    allow_git_status = engine.evaluate(["git", "status"], _ctx())

    assert allow_ls.allow is True
    assert allow_ls.policy_id == "rules.v1.allow"
    assert allow_git_status.allow is True
    assert allow_git_status.policy_id == "rules.v1.allow"


def test_policy_engine_denies_unapproved_commands() -> None:
    engine = PolicyEngine(allow_high_risk=False)

    deny_sudo = engine.evaluate(["sudo", "ls"], _ctx())
    deny_rm = engine.evaluate(["rm", "-rf", "/tmp/x"], _ctx())

    assert deny_sudo.allow is False
    assert "not approved" in deny_sudo.reason.lower()
    assert deny_sudo.policy_id == "rules.v1.base_command_denied"
    assert deny_rm.allow is False
    assert deny_rm.policy_id == "rules.v1.base_command_denied"


def test_policy_engine_denies_empty_command_parts() -> None:
    engine = PolicyEngine(allow_high_risk=False)

    decision = engine.evaluate([], _ctx())

    assert decision.allow is False
    assert decision.policy_id == "baseline.v1.empty"


def test_policy_engine_denies_high_risk_when_disabled() -> None:
    engine = PolicyEngine(allow_high_risk=False)

    decision = engine.evaluate(["git", "status"], _ctx(risk_level="high"))

    assert decision.allow is False
    assert decision.policy_id == "baseline.v1.high_risk_denied"
    assert "high-risk" in decision.reason.lower()
