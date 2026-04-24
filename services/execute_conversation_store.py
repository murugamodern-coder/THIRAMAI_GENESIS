"""Persistent conversation storage for `/execute` (PostgreSQL/SQLite via SQLAlchemy)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Select, select

from core.database import get_session_factory
from core.db.models import Conversation, ConversationMessage


def _short_title(command: str) -> str:
    text = " ".join(str(command or "").strip().split())
    if not text:
        return "New conversation"
    return text[:80]


def _assistant_content(payload: dict[str, Any]) -> str:
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()[:2000]
    if isinstance(result, dict):
        for key in ("summary", "message", "overview", "insight", "title"):
            v = result.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:2000]
        try:
            return json.dumps(result, ensure_ascii=False)[:2000]
        except Exception:
            return "Execution completed."
    return "Execution completed."


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def list_user_conversations(user_id: int, limit: int = 40) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 100))
    with factory() as session:
        q: Select[tuple[Conversation]] = (
            select(Conversation)
            .where(Conversation.user_id == int(user_id))
            .order_by(Conversation.created_at.desc())
            .limit(lim)
        )
        rows = session.execute(q).scalars().all()
        return [
            {
                "id": int(c.id),
                "title": str(c.title or "New conversation"),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ]


def list_conversation_messages(user_id: int, conversation_id: int, limit: int = 200) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 400))
    with factory() as session:
        owned = session.execute(
            select(Conversation.id).where(
                Conversation.id == int(conversation_id),
                Conversation.user_id == int(user_id),
            )
        ).scalar_one_or_none()
        if owned is None:
            return []
        q: Select[tuple[ConversationMessage]] = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == int(conversation_id))
            .order_by(ConversationMessage.created_at.asc(), ConversationMessage.id.asc())
            .limit(lim)
        )
        rows = session.execute(q).scalars().all()
        return [
            {
                "id": int(m.id),
                "conversation_id": int(m.conversation_id),
                "role": str(m.role),
                "content": str(m.content or ""),
                "metadata": m.metadata_json or {},
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ]


def get_recent_context_messages(user_id: int, conversation_id: int | None, limit: int = 8) -> list[dict[str, Any]]:
    if conversation_id is None:
        return []
    msgs = list_conversation_messages(user_id=user_id, conversation_id=conversation_id, limit=max(1, limit))
    if not msgs:
        return []
    return msgs[-limit:]


def persist_execute_exchange(
    *,
    user_id: int,
    command: str,
    assistant_payload: dict[str, Any],
    conversation_id: int | None = None,
) -> int | None:
    factory = _session_factory_or_none()
    if factory is None:
        return conversation_id
    with factory() as session:
        conversation: Conversation | None = None
        if conversation_id is not None:
            conversation = session.execute(
                select(Conversation).where(
                    Conversation.id == int(conversation_id),
                    Conversation.user_id == int(user_id),
                )
            ).scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(user_id=int(user_id), title=_short_title(command))
            session.add(conversation)
            session.flush()

        session.add(
            ConversationMessage(
                conversation_id=int(conversation.id),
                role="user",
                content=str(command or ""),
                metadata_json={},
            )
        )
        session.add(
            ConversationMessage(
                conversation_id=int(conversation.id),
                role="assistant",
                content=_assistant_content(assistant_payload),
                metadata_json=assistant_payload,
            )
        )
        session.commit()
        return int(conversation.id)
