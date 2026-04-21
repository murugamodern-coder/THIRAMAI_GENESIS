from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import types

import pytest

import thiramai.core.executor as executor_mod
from thiramai.core.executor import Executor, PolicyViolationError, UnsafeCommandError
from thiramai.core.logger import SecurityLogger
from thiramai.main import JarvisCore
from thiramai.policy.models import ExecutionContext


def _blocked_result_from_exception(exc: Exception, command: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "returncode": -1,
        "output": "",
        "error": str(exc),
        "ok": False,
        "stdout": "",
        "stderr": str(exc),
        "exit_code": -1,
        "command": command,
        "policy_decision": {
            "allow": False,
            "policy_id": getattr(exc, "policy_id", type(exc).__name__),
            "reason": getattr(exc, "reason", str(exc)),
        },
    }


def _run_attack(
    *,
    engine: JarvisCore,
    cycle_id: int,
    attack_id: str,
    command: str,
    task_type: str,
    risk_level: str = "low",
) -> dict[str, Any]:
    ctx = ExecutionContext(task_type=task_type, risk_level=risk_level, capabilities=[])
    try:
        result = engine.executor.execute_command(command, context=ctx)
    except (PolicyViolationError, UnsafeCommandError) as exc:
        result = _blocked_result_from_exception(exc, command)
    task = {
        "id": attack_id,
        "type": task_type,
        "description": f"red-team attack {attack_id}",
        "command": command,
        "risk_level": risk_level,
    }
    engine._audit_execution(cycle_id=cycle_id, task_id=attack_id, task=task, result=result)
    return result


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw:
            continue
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def test_red_team_attack_suite_logs_blocked_attempts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = JarvisCore(goal="red team", fixed_goal_only=True)
    audit_path = tmp_path / "audit_trail.jsonl"
    engine.security_logger = SecurityLogger(file_path=audit_path)
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "strict")
    monkeypatch.setattr(executor_mod, "THIRAMAI_USE_DOCKER", True)
    monkeypatch.setattr(executor_mod, "THIRAMAI_DOCKER_NETWORK_ENABLED", False)

    captured: dict[str, Any] = {}

    class _FakeContainers:
        def run(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return b"ok"

    class _FakeDockerClient:
        containers = _FakeContainers()

    fake_docker_module = types.ModuleType("docker")
    fake_docker_errors = types.ModuleType("docker.errors")

    class _ContainerError(Exception):
        pass

    class _DockerException(Exception):
        pass

    fake_docker_errors.ContainerError = _ContainerError
    fake_docker_errors.DockerException = _DockerException
    fake_docker_module.from_env = lambda: _FakeDockerClient()  # type: ignore[attr-defined]
    fake_docker_module.errors = fake_docker_errors  # type: ignore[attr-defined]

    import sys

    monkeypatch.setitem(sys.modules, "docker", fake_docker_module)
    monkeypatch.setitem(sys.modules, "docker.errors", fake_docker_errors)

    attacks = [
        # Path traversal / private key exfil attempt
        ("atk-path-traversal", "python -m py_compile ../../etc/shadow", "audit"),
        ("atk-ssh-key-read", "python -m py_compile ../../.ssh/id_rsa", "audit"),
        # Command chaining attempt
        ("atk-command-chaining", "ls && rm -rf /workspace", "audit"),
        # Policy obfuscation / shell nesting
        ("atk-obfuscation", "python -c import base64,os;exec(base64.b64decode('cm0gLXJmIC93b3Jrc3BhY2U='))", "analysis"),
    ]
    for attack_id, command, task_type in attacks:
        out = _run_attack(
            engine=engine,
            cycle_id=9001,
            attack_id=attack_id,
            command=command,
            task_type=task_type,
        )
        assert out.get("status") == "blocked"

    rows = _load_jsonl(audit_path)
    attack_rows = [r for r in rows if str(r.get("task_id", "")).startswith("atk-")]
    assert len(attack_rows) == len(attacks)
    assert all(str(r.get("execution_status", "")).lower() == "blocked" for r in attack_rows)


def test_red_team_read_only_violation_in_audit_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = JarvisCore(goal="red team", fixed_goal_only=True)
    audit_path = tmp_path / "audit_trail.jsonl"
    engine.security_logger = SecurityLogger(file_path=audit_path)
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "strict")
    monkeypatch.setattr(executor_mod, "THIRAMAI_USE_DOCKER", True)

    def fake_docker_exec(parts: list[str], command: str, *, context: ExecutionContext | None = None) -> dict[str, Any]:
        _ = parts
        _ = command
        task_type = str((context or ExecutionContext()).task_type).lower()
        if task_type in {"audit", "analysis"}:
            return {
                "status": "blocked",
                "returncode": 13,
                "output": "",
                "error": "read-only workspace mount denied write",
                "ok": False,
                "stdout": "",
                "stderr": "read-only workspace mount denied write",
                "exit_code": 13,
                "policy_decision": {"allow": False, "policy_id": "docker.ro_guard", "reason": "read-only mount"},
                "execution_backend": "docker",
            }
        return {
            "status": "success",
            "returncode": 0,
            "output": "ok",
            "error": "",
            "ok": True,
            "stdout": "ok",
            "stderr": "",
            "exit_code": 0,
            "policy_decision": {"allow": True, "policy_id": "rules.v1.allow", "reason": "allowed"},
            "execution_backend": "docker",
        }

    monkeypatch.setattr(engine.executor, "_execute_in_docker", fake_docker_exec)
    out = _run_attack(
        engine=engine,
        cycle_id=9002,
        attack_id="atk-ro-violation",
        command="git status",
        task_type="audit",
    )
    assert out["status"] == "blocked"
    assert "read-only" in out["error"]


def test_red_team_resource_exhaustion_hits_docker_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    ex = Executor()
    monkeypatch.setattr(executor_mod, "THIRAMAI_USE_DOCKER", True)
    monkeypatch.setattr(executor_mod, "THIRAMAI_POLICY_MODE", "strict")

    captured: dict[str, Any] = {}

    class _FakeContainers:
        def run(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return b"ok"

    class _FakeDockerClient:
        containers = _FakeContainers()

    fake_docker_module = types.ModuleType("docker")
    fake_docker_errors = types.ModuleType("docker.errors")

    class _ContainerError(Exception):
        pass

    class _DockerException(Exception):
        pass

    fake_docker_errors.ContainerError = _ContainerError
    fake_docker_errors.DockerException = _DockerException
    fake_docker_module.from_env = lambda: _FakeDockerClient()  # type: ignore[attr-defined]
    fake_docker_module.errors = fake_docker_errors  # type: ignore[attr-defined]

    import sys

    monkeypatch.setitem(sys.modules, "docker", fake_docker_module)
    monkeypatch.setitem(sys.modules, "docker.errors", fake_docker_errors)

    ctx = ExecutionContext(task_type="coding", risk_level="low", capabilities=[])
    result = ex.execute_command("python -m compileall .", context=ctx)
    assert result["status"] == "success"
    assert captured.get("nano_cpus") == 500_000_000
    assert captured.get("mem_limit") == "512m"
    assert captured.get("network_disabled") in {True, False}
    assert "/tmp/thiramai_scratch" in (captured.get("tmpfs") or {})
