from typing import Any

from thiramai.integrations.search import search_web


class ResearchAgent:
    def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        query = str(task.get("query", task.get("description", "system reliability audit fixes"))).strip()
        findings = search_web(query=query, limit=5)
        return {
            "ok": True,
            "query": query,
            "findings": findings,
        }
