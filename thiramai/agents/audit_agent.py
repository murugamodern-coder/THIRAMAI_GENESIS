from typing import Any

from thiramai.core.executor import Executor
from thiramai.policy.models import ExecutionContext


class AuditAgent:
    DEFAULT_AUDIT_COMMANDS = [
        "pwd",
        "ls",
        "git status",
        "docker ps",
        "python --version",
        "pip --version",
    ]

    def execute(self, task: dict[str, Any], executor: Executor, context: dict[str, Any]) -> dict[str, Any]:
        task_type = str(task.get("type", "audit")).lower()
        risk_level = str(task.get("risk_level", "low")).lower()
        exec_context = ExecutionContext(
            tenant_id=None,
            task_type=task_type if task_type in {"audit", "analysis", "coding", "research", "fix", "api", "device"} else "audit",
            risk_level=risk_level if risk_level in {"low", "medium", "high"} else "low",
            capabilities=[str(x) for x in task.get("capabilities", []) if str(x).strip()],
        )
        command = str(task.get("command", "")).strip()
        if not command:
            sequence_results: list[dict[str, Any]] = []
            for cmd in self.DEFAULT_AUDIT_COMMANDS:
                sequence_results.append(executor.execute_command(cmd, context=exec_context))
            return {
                "ok": all(item.get("ok", False) for item in sequence_results),
                "mode": "audit_sequence",
                "results": sequence_results,
            }
        return executor.execute_command(command, context=exec_context)
