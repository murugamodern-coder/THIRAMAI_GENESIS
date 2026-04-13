"""Jarvis user memory (preferences / facts) for personalized prompts."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import JarvisMemory

_log = logging.getLogger("thiramai.jarvis_memory")


def fetch_memory_context_lines_sync(*, user_id: int, limit: int = 8) -> list[str]:
    uid = int(user_id)
    if uid <= 0:
        return []
    factory = get_session_factory()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 24))
    with factory() as session:
        rows = list(
            session.scalars(
                select(JarvisMemory)
                .where(JarvisMemory.user_id == uid)
                .order_by(JarvisMemory.usage_count.desc(), JarvisMemory.last_updated.desc())
                .limit(lim)
            ).all()
        )
    out: list[str] = []
    for r in rows:
        k = (r.memory_key or "").strip()
        v = (r.memory_value or "").strip()
        if k and v:
            out.append(f"- {k}: {v}")
    return out


def upsert_memory_sync(
    *,
    user_id: int,
    memory_key: str,
    memory_value: str,
    confidence: float = 0.6,
) -> dict[str, Any]:
    uid = int(user_id)
    k = (memory_key or "").strip()[:512]
    v = (memory_value or "").strip()[:4000]
    if uid <= 0 or not k or not v:
        return {"ok": False, "error": "user_id, memory_key, memory_value required"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "database not configured"}
    conf = Decimal(str(confidence)).quantize(Decimal("0.01"))
    try:
        with factory() as session:
            with session.begin():
                existing = session.execute(
                    select(JarvisMemory).where(JarvisMemory.user_id == uid, JarvisMemory.memory_key == k).limit(1)
                ).scalar_one_or_none()
                if existing:
                    existing.memory_value = v
                    existing.confidence = conf
                    existing.usage_count = int(existing.usage_count or 0) + 1
                else:
                    session.add(
                        JarvisMemory(
                            user_id=uid,
                            memory_key=k,
                            memory_value=v,
                            confidence=conf,
                            usage_count=1,
                        )
                    )
        return {"ok": True}
    except Exception as exc:
        _log.warning("upsert_memory failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def bump_memory_usage_sync(*, user_id: int, memory_keys: list[str]) -> None:
    if not memory_keys:
        return
    uid = int(user_id)
    factory = get_session_factory()
    if factory is None or uid <= 0:
        return
    keys = [str(x).strip()[:512] for x in memory_keys if str(x).strip()]
    if not keys:
        return
    try:
        with factory() as session:
            with session.begin():
                for k in keys:
                    row = session.execute(
                        select(JarvisMemory).where(JarvisMemory.user_id == uid, JarvisMemory.memory_key == k).limit(1)
                    ).scalar_one_or_none()
                    if row:
                        row.usage_count = int(row.usage_count or 0) + 1
    except Exception:
        _log.debug("bump_memory_usage ignored", exc_info=True)
