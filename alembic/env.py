"""
Alembic environment — uses DATABASE_URL and SQLAlchemy Base metadata.

**Schema changes:** add a new revision under ``alembic/versions/`` only; do not hand-edit
production databases outside Alembic (baseline ``0001`` may apply ``db/*.sql`` once on empty DB).
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Project root on sys.path (alembic.ini prepend_sys_path = .)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.env_bootstrap import load_project_dotenv  # noqa: E402

load_project_dotenv(root=ROOT)

from core.database import get_database_url, normalize_database_url  # noqa: E402
from core.db.base import Base  # noqa: E402

# Register all models on Base.metadata
import core.db.models  # noqa: E402, F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    url = get_database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set — required for Alembic.")
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (engine connection)."""
    url = _sync_url()
    connectable = engine_from_config(
        {"sqlalchemy.url": url, "sqlalchemy.poolclass": pool.NullPool},
        prefix="sqlalchemy.",
    )
    with connectable.connect() as connection:
        if connection.dialect.name != "postgresql":
            raise RuntimeError(
                f"Alembic baseline migrations target PostgreSQL; got dialect {connection.dialect.name!r}. "
                "Use SQLite only for local pytest without running these revisions."
            )
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
