"""Baseline: apply ordered DDL from repository ``db/*.sql`` (PostgreSQL).

Revision ID: 0001
Revises:
Create Date: 2026-03-30

Irreversible: use backup/restore to roll back schema.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from core.migration_sql import SQL_BASELINE_FILES, apply_sql_files

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    apply_sql_files(SQL_BASELINE_FILES)
    # Default Alembic column is VARCHAR(32); revision ids in this repo exceed that.
    op.execute(sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))


def downgrade() -> None:
    raise NotImplementedError(
        "Baseline downgrade is not supported — restore from backup or create a forward migration."
    )
