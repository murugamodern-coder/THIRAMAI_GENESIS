"""User integrations (Google Calendar) + personal_meetings.google_event_id.

Revision ID: 0030_user_integrations_google_calendar
Revises: 0029_personal_meetings
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_user_integrations_google_calendar"
down_revision: Union[str, Sequence[str], None] = "0029_personal_meetings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind is not None and bind.dialect.name == "postgresql"
    meta_col_type = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    meta_default = sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")

    op.create_table(
        "user_integrations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("integration_type", sa.String(length=64), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("meta_json", meta_col_type, nullable=False, server_default=meta_default),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()") if is_pg else sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()") if is_pg else sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "integration_type", name="uq_user_integrations_user_type"),
    )
    op.create_index("ix_user_integrations_user_id", "user_integrations", ["user_id"], unique=False)
    op.create_index("ix_user_integrations_type", "user_integrations", ["integration_type"], unique=False)

    op.add_column(
        "personal_meetings",
        sa.Column("google_event_id", sa.String(length=256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("personal_meetings", "google_event_id")
    op.drop_index("ix_user_integrations_type", table_name="user_integrations")
    op.drop_index("ix_user_integrations_user_id", table_name="user_integrations")
    op.drop_table("user_integrations")
