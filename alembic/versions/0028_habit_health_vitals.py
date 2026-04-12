"""Widen alembic_version.version_num, then habit category + health_logs vitals.

Revision ID: 0028_habit_health_vitals
Revises: 0027_personal_command_center

Production Postgres often ships alembic_version.version_num as VARCHAR(32); longer
revision strings must widen the column before Alembic records this migration.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_habit_health_vitals"
down_revision: Union[str, Sequence[str], None] = "0027_personal_command_center"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else ""

    if dialect == "postgresql":
        op.execute(sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"))
    else:
        with op.batch_alter_table("alembic_version") as batch_op:
            batch_op.alter_column(
                "version_num",
                existing_type=sa.String(length=32),
                type_=sa.String(length=255),
                existing_nullable=False,
            )

    op.add_column("habits", sa.Column("category", sa.String(length=32), nullable=True))

    op.add_column("health_logs", sa.Column("weight_kg", sa.Numeric(6, 2), nullable=True))
    op.add_column("health_logs", sa.Column("bp_systolic", sa.Integer(), nullable=True))
    op.add_column("health_logs", sa.Column("bp_diastolic", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("habits", "category")
    op.drop_column("health_logs", "bp_diastolic")
    op.drop_column("health_logs", "bp_systolic")
    op.drop_column("health_logs", "weight_kg")

    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        op.execute(
            sa.text(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32) "
                "USING LEFT(version_num::text, 32)"
            )
        )
    else:
        with op.batch_alter_table("alembic_version") as batch_op:
            batch_op.alter_column(
                "version_num",
                existing_type=sa.String(length=255),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
