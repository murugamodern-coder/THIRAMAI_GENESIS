"""Habit category + optional vitals on daily health_logs for Life OS quick entry.

Revision ID: 0028_habit_category_health_log_vitals
Revises: 0027_personal_command_center
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_habit_category_health_log_vitals"
down_revision: Union[str, Sequence[str], None] = "0027_personal_command_center"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("habits", sa.Column("category", sa.String(length=32), nullable=True))

    op.add_column("health_logs", sa.Column("weight_kg", sa.Numeric(6, 2), nullable=True))
    op.add_column("health_logs", sa.Column("bp_systolic", sa.Integer(), nullable=True))
    op.add_column("health_logs", sa.Column("bp_diastolic", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("habits", "category")
    op.drop_column("health_logs", "bp_diastolic")
    op.drop_column("health_logs", "bp_systolic")
    op.drop_column("health_logs", "weight_kg")
