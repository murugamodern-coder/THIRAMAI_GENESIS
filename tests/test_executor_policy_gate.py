from __future__ import annotations

from unittest.mock import Mock

import pytest

import thiramai.core.executor as executor_mod
from thiramai.core.executor import Executor, PolicyViolationError, UnsafeCommandError
from thiramai.policy.models import ExecutionContext


def test_execute_command_raises_policy_violation_when_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = Executor()
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "strict")
    deny = Mock(return_value=Mock(allow=False, reason="blocked by test policy", policy_id="test.policy.deny"))
    monkeypatch.setattr(ex.policy_engine, "evaluate", deny)

    with pytest.raises(PolicyViolationError, match="test.policy.deny"):
        ex.execute_command("git status", context=ExecutionContext(task_type="audit", risk_level="low"))


def test_strict_mode_uses_policy_engine_only(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = Executor()
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "strict")
    monkeypatch.setattr(ex, "_validate_blocked_tokens", Mock(side_effect=AssertionError("legacy path should not run")))
    monkeypatch.setattr(ex.policy_engine, "evaluate", Mock(return_value=Mock(allow=True, reason="ok", policy_id="allow")))

    parts = ex._validate_command("git status", context=ExecutionContext(task_type="audit", risk_level="low"))

    assert parts == ["git", "status"]
    ex.policy_engine.evaluate.assert_called_once()


def test_hybrid_mode_consults_legacy_and_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = Executor()
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "hybrid")

    blocked_probe = Mock()
    args_probe = Mock()
    policy_probe = Mock(return_value=Mock(allow=True, reason="ok", policy_id="allow"))
    monkeypatch.setattr(ex, "_validate_blocked_tokens", blocked_probe)
    monkeypatch.setattr(ex, "_validate_arguments", args_probe)
    monkeypatch.setattr(ex.policy_engine, "evaluate", policy_probe)

    parts = ex._validate_command("git status", context=ExecutionContext(task_type="audit", risk_level="low"))

    assert parts == ["git", "status"]
    blocked_probe.assert_called_once_with(["git", "status"])
    args_probe.assert_called_once_with(["git", "status"])
    policy_probe.assert_called_once()


def test_hybrid_mode_still_blocks_legacy_denied_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = Executor()
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "hybrid")
    monkeypatch.setattr(ex.policy_engine, "evaluate", Mock(return_value=Mock(allow=True, reason="ok", policy_id="allow")))

    with pytest.raises(UnsafeCommandError, match="allowlist"):
        ex._validate_command("sudo ls", context=ExecutionContext(task_type="audit", risk_level="low"))
