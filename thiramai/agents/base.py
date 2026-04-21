from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from thiramai.core.knowledge import LocalKnowledgeBase
from thiramai.tools.search_tool import SearchTool

@dataclass
class AgentMessage:
    sender: str
    recipient: str
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MessageBus:
    def __init__(self) -> None:
        self._messages: list[AgentMessage] = []

    def publish(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def drain_for(self, recipient: str) -> list[AgentMessage]:
        target = str(recipient).strip().lower()
        out: list[AgentMessage] = []
        keep: list[AgentMessage] = []
        for msg in self._messages:
            if msg.recipient.lower() in {target, "all"}:
                out.append(msg)
            else:
                keep.append(msg)
        self._messages = keep
        return out


class BaseAgent:
    NAME = "base_agent"

    def __init__(self, bus: MessageBus) -> None:
        self.bus = bus

    def assign(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            **task,
            "assigned_agent": self.NAME,
            "security_monitored": True,  # JarvisCore keeps central security supervision.
        }

    def publish(self, *, recipient: str, topic: str, payload: dict[str, Any]) -> None:
        self.bus.publish(
            AgentMessage(
                sender=self.NAME,
                recipient=recipient,
                topic=topic,
                payload=payload,
            )
        )


class ResearcherAgent(BaseAgent):
    NAME = "researcher_agent"
    _search = SearchTool()
    _knowledge = LocalKnowledgeBase()

    def assign(self, task: dict[str, Any]) -> dict[str, Any]:
        out = super().assign(task)
        query = str(task.get("search_query") or task.get("description") or task.get("goal") or "").strip()
        local_hits = self._knowledge.retrieve(query, limit=5) if query else []
        local_summary = self._knowledge.summarize(local_hits) if local_hits else ""
        web_used = False
        search_bundle: dict[str, Any]
        if local_hits:
            search_bundle = {"ok": True, "results": [], "summary": ""}
        else:
            web_used = True
            search_bundle = (
                self._search.search_and_summarize(query, top_k=5)
                if query
                else {"ok": False, "results": [], "summary": ""}
            )
        out["search_query"] = query
        out["knowledge_results"] = local_hits
        out["knowledge_summary"] = local_summary
        out["search_results"] = search_bundle.get("results", [])
        out["web_search_used"] = web_used
        out["research_summary"] = local_summary or search_bundle.get("summary", "")
        self.publish(
            recipient="coder_agent",
            topic="research_handoff",
            payload={
                "task_id": out.get("id"),
                "query": query,
                "summary": out.get("research_summary", ""),
                "knowledge_results": out.get("knowledge_results", []),
                "results": out.get("search_results", []),
                "web_search_used": web_used,
            },
        )
        return out


class CoderAgent(BaseAgent):
    NAME = "coder_agent"

    def assign(self, task: dict[str, Any]) -> dict[str, Any]:
        out = super().assign(task)
        inbox = self.bus.drain_for(self.NAME)
        if inbox:
            out["message_bus_inputs"] = [
                {"from": m.sender, "topic": m.topic, "payload": m.payload}
                for m in inbox
            ]
        self.publish(recipient="reviewer_agent", topic="implementation_handoff", payload={"task_id": out.get("id")})
        return out


class ReviewerAgent(BaseAgent):
    NAME = "reviewer_agent"

    def assign(self, task: dict[str, Any]) -> dict[str, Any]:
        out = super().assign(task)
        inbox = self.bus.drain_for(self.NAME)
        if inbox:
            out["message_bus_inputs"] = [
                {"from": m.sender, "topic": m.topic, "payload": m.payload}
                for m in inbox
            ]
        return out
