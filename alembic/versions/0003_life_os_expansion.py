"""Phase 3 Life OS: habits, habit_logs, personal_missions, personal_health_metrics, enc_notes.

Revision ID: 0003_life_os_expansion
Revises: 0002_multi_tenant_membership

Flexible time-series health (metric_type sleep/steps/mood, etc.) is stored in ``personal_health_metrics``
because the existing ``health_logs`` table is the legacy **daily aggregate** row (``HealthLog``) and
cannot be reused without breaking that schema. Fernet ciphertext for ``enc_notes`` uses either per-user
vault keys or ``VAULT_PASSPHRASE``-derived server Fernet during vault JSON migration (see ``life_os_service``).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_life_os_expansion"
down_revision: Union[str, Sequence[str], None] = "0002_multi_tenant_membership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "habits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("goal_frequency", sa.Text(), nullable=False, server_default="daily"),
        sa.Column("streak_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_habits_user_id", "habits", ["user_id"], unique=False)

    op.create_table(
        "habit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("habit_id", sa.BigInteger(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_habit_logs_habit_id", "habit_logs", ["habit_id"], unique=False)

    op.create_table(
        "personal_missions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("source_ref", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_missions_user_id", "personal_missions", ["user_id"], unique=False)
    op.create_index("ix_personal_missions_source_ref", "personal_missions", ["source_ref"], unique=False)

    op.create_table(
        "personal_health_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("metric_type", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_health_metrics_user_id", "personal_health_metrics", ["user_id"], unique=False
    )
    op.create_index(
        "ix_personal_health_metrics_metric_type", "personal_health_metrics", ["metric_type"], unique=False
    )
    op.create_index(
        "ix_personal_health_metrics_user_recorded",
        "personal_health_metrics",
        ["user_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "enc_notes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("encrypted_content", sa.LargeBinary(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_enc_notes_user_id", "enc_notes", ["user_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("0003 downgrade not implemented.")
