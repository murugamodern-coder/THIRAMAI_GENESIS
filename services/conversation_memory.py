"""Per-user, per-org Redis-backed conversation history for Central Brain chat."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger(__name__)


class ConversationMemory:
    def __init__(self, redis_client: Any, user_id: int | str, org_id: int | str):
        self.redis = redis_client
        self.key = f"thiramai:chat:{org_id}:{user_id}"
        self.max_messages = 20

    async def add_message(self, role: str, content: str, routing: str | None = None) -> None:
        """Add message to conversation history."""
        if self.redis is None:
            return
        message = {
            "role": role,
            "content": content,
            "routing": routing,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            payload = json.dumps(message, ensure_ascii=False)
            await self.redis.lpush(self.key, payload)
            await self.redis.ltrim(self.key, 0, self.max_messages - 1)
            await self.redis.expire(self.key, 86400 * 7)
        except Exception as exc:
            _log.warning("conversation_memory add_message failed: %s", exc)

    async def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent conversation history (oldest → newest among the last ``limit`` messages)."""
        if self.redis is None:
            return []
        lim = max(1, min(int(limit), self.max_messages))
        try:
            messages = await self.redis.lrange(self.key, 0, lim - 1)
            return [json.loads(m) for m in reversed(messages)]
        except Exception as exc:
            _log.warning("conversation_memory get_history failed: %s", exc)
            return []

    async def clear(self) -> None:
        """Clear conversation history."""
        if self.redis is None:
            return
        try:
            await self.redis.delete(self.key)
        except Exception as exc:
            _log.warning("conversation_memory clear failed: %s", exc)

    def format_for_llm(self, history: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Format history for Groq/OpenAI-style chat APIs."""
        formatted: list[dict[str, str]] = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "assistant"
            formatted.append({"role": role, "content": str(msg.get("content") or "")})
        return formatted
