"""Persistent idempotency in PostgreSQL / SQLite via ``idempotency_keys`` (DB transactions)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import IdempotencyKey

StaleDecision = Literal["run", "duplicate"]


def _stale_minutes() -> int:
    raw = (os.getenv("THIRAMAI_IDEMPOTENCY_STALE_MINUTES") or "120").strip()
    try:
        return max(5, min(10_080, int(raw)))
    except ValueError:
        return 120


def _require_factory() -> sessionmaker[Session]:
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError(
            "DATABASE_URL is not configured; idempotency requires a database "
            "(apply db/idempotency_and_jobs.sql)."
        )
    return factory


def try_claim_idempotency_slot(idempotency_key: str, action_type: str) -> StaleDecision:
    """
    Claim exclusive right to run work for ``idempotency_key``.

    Returns ``run`` if this caller should execute; ``duplicate`` if already completed or
    another execution is in progress (unless the in-flight row is stale, then it is removed).
    """
    if not idempotency_key or not str(idempotency_key).strip():
        raise ValueError("idempotency_key is required")
    key = str(idempotency_key).strip()
    factory = _require_factory()
    stale_after = timedelta(minutes=_stale_minutes())

    try:
        with factory() as session:
            with session.begin():
                existing = session.scalar(
                    select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key).with_for_update()
                )
                if existing is not None:
                    if existing.completed_at is not None:
                        return "duplicate"
                    created = existing.created_at
                    if created is not None:
                        if created.tzinfo is None:
                            created = created.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) - created <= stale_after:
                            return "duplicate"
                    session.delete(existing)
                    session.flush()

                session.add(
                    IdempotencyKey(
                        idempotency_key=key,
                        action_type=action_type or "",
                        meta={},
                        completed_at=None,
                    )
                )
                session.flush()
        return "run"
    except IntegrityError:
        with factory() as session:
            row2 = session.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key))
            if row2 and row2.completed_at is not None:
                return "duplicate"
            return "duplicate"


def mark_idempotency_completed(
    idempotency_key: str,
    *,
    action_type: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    """Set ``completed_at`` and merge ``meta`` after successful side effects."""
    key = str(idempotency_key).strip()
    factory = _require_factory()
    payload = dict(meta or {})
    if action_type:
        payload.setdefault("action_type", action_type)
    with factory() as session:
        with session.begin():
            session.execute(
                update(IdempotencyKey)
                .where(IdempotencyKey.idempotency_key == key)
                .values(
                    completed_at=datetime.now(timezone.utc),
                    meta=payload,
                )
            )


def release_idempotency_claim(idempotency_key: str) -> None:
    """Remove in-flight row after failure so callers may retry."""
    key = str(idempotency_key).strip()
    factory = _require_factory()
    with factory() as session:
        with session.begin():
            session.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.idempotency_key == key,
                    IdempotencyKey.completed_at.is_(None),
                )
            )


def has_completed(idempotency_key: str) -> bool:
    """True if key exists with ``completed_at`` set (read-only check)."""
    key = str(idempotency_key).strip()
    factory = _require_factory()
    with factory() as session:
        row = session.scalar(
            select(IdempotencyKey).where(IdempotencyKey.idempotency_key == key),
        )
        return row is not None and row.completed_at is not None


def mark_completed(key: str, *, action_type: str = "", meta: dict[str, Any] | None = None) -> None:
    """Backward-compatible alias — delegates to ``mark_idempotency_completed``."""
    mark_idempotency_completed(key, action_type=action_type, meta=meta)
