"""Shared DB session-factory helpers to avoid duplicated fallback logic."""

from __future__ import annotations

from typing import Any

from core.database import get_session_factory


def get_session_factory_safe() -> Any | None:
    """Return session factory or None without throwing."""
    try:
        return get_session_factory()
    except Exception:
        return None

