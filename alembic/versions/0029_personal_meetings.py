"""Personal meetings / appointments (Personal OS).

Revision ID: 0029_personal_meetings
Revises: 0028_habit_health_vitals
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_personal_meetings"
down_revision: Union[str, Sequence[str], None] = "0028_habit_health_vitals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind is not None and bind.dialect.name == "postgresql"
    attendees_col_type = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    attendees_default = sa.text("'[]'::jsonb") if is_pg else sa.text("'[]'")

    op.create_table(
        "personal_meetings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("meeting_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("location_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("location_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("location_address", sa.Text(), nullable=True),
        sa.Column("location_maps_url", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("agenda", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("arranged_by", sa.String(length=16), nullable=False, server_default="self"),
        sa.Column("organizer_name", sa.Text(), nullable=True),
        sa.Column("organizer_phone", sa.String(length=64), nullable=True),
        sa.Column("organizer_email", sa.String(length=320), nullable=True),
        sa.Column(
            "attendees_json",
            attendees_col_type,
            nullable=False,
            server_default=attendees_default,
        ),
        sa.Column("reminder_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("recurrence_rule", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_meetings_user_id", "personal_meetings", ["user_id"])
    op.create_index("ix_personal_meetings_org_id", "personal_meetings", ["organization_id"])
    op.create_index("ix_personal_meetings_scheduled_at", "personal_meetings", ["scheduled_at"])
    op.create_index("ix_personal_meetings_status", "personal_meetings", ["status"])
    op.create_index("ix_personal_meetings_user_scheduled", "personal_meetings", ["user_id", "scheduled_at"])


def downgrade() -> None:
    op.drop_index("ix_personal_meetings_user_scheduled", table_name="personal_meetings")
    op.drop_index("ix_personal_meetings_status", table_name="personal_meetings")
    op.drop_index("ix_personal_meetings_scheduled_at", table_name="personal_meetings")
    op.drop_index("ix_personal_meetings_org_id", table_name="personal_meetings")
    op.drop_index("ix_personal_meetings_user_id", table_name="personal_meetings")
    op.drop_table("personal_meetings")
