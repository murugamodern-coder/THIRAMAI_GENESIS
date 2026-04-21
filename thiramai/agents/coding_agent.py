import json
from typing import Any

from thiramai.core.executor import Executor
from thiramai.integrations.llm_clients import call_llm
from thiramai.policy.models import ExecutionContext


class CodingAgent:
    def execute(self, task: dict[str, Any], executor: Executor, context: dict[str, Any]) -> dict[str, Any]:
        task_type = str(task.get("type", "coding")).lower()
        risk_level = str(task.get("risk_level", "low")).lower()
        exec_context = ExecutionContext(
            tenant_id=None,
            task_type=task_type if task_type in {"audit", "analysis", "coding", "research", "fix", "api", "device"} else "coding",
            risk_level=risk_level if risk_level in {"low", "medium", "high"} else "low",
            capabilities=[str(x) for x in task.get("capabilities", []) if str(x).strip()],
        )
        if task.get("command"):
            return executor.execute_command(str(task["command"]), context=exec_context)

        prompt = (
            "Based on this context, produce one safe shell command to fix a concrete issue. "
            "Allowed categories: diagnostics, dependency install, formatting, tests. "
            "Return ONLY the command string.\n"
            f"{json.dumps({'task': task, 'context': context}, ensure_ascii=True)}"
        )
        generated_command = call_llm(prompt).strip().splitlines()[0].strip()
        execution = executor.execute_command(generated_command, context=exec_context)
        execution["generated_command"] = generated_command
        return execution
