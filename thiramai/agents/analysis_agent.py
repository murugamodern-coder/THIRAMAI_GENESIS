import json
from typing import Any

from thiramai.integrations.llm_clients import call_llm


class AnalysisAgent:
    def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "task": task,
            "latest_results": context.get("latest_results", []),
            "failures": context.get("failures", []),
        }
        prompt = (
            "Analyze the autonomous run output and produce concise findings in plain text. "
            "Focus on failed commands and likely safe remediation steps.\n"
            f"{json.dumps(payload, ensure_ascii=True)}"
        )
        analysis = call_llm(prompt)
        return {"ok": True, "analysis": analysis}
