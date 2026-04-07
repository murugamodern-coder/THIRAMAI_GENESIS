"""Deprecated: use `core.database` for engine and sessions."""

from core.database import (  # noqa: F401
    get_database_url,
    get_engine,
    get_session_factory,
    normalize_database_url,
    ping_database,
    reset_engine_cache,
    session_scope,
    structured_vault_ready,
)

__all__ = [
    "get_database_url",
    "get_engine",
    "get_session_factory",
    "normalize_database_url",
    "ping_database",
    "reset_engine_cache",
    "session_scope",
    "structured_vault_ready",
]
