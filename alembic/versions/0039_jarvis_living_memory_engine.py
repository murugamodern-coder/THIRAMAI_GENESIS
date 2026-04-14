"""Living Jarvis Upgrade 1 — episodic, semantic, and session working memory.

Revision ID: 0039_jarvis_living_memory_engine
Revises: 0038_week1_query_indexes
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039_jarvis_living_memory_engine"
down_revision: Union[str, Sequence[str], None] = "0038_week1_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jarvis_episodes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("episode_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("importance", sa.SmallInteger(), nullable=False, server_default="5"),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jarvis_episodes_user_created", "jarvis_episodes", ["user_id", "created_at"], unique=False)
    op.create_index("ix_jarvis_episodes_user_type", "jarvis_episodes", ["user_id", "episode_type"], unique=False)
    op.create_index(op.f("ix_jarvis_episodes_expires_at"), "jarvis_episodes", ["expires_at"], unique=False)

    op.create_table(
        "jarvis_facts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("fact_type", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False, server_default="0.7"),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="jarvis"),
        sa.Column("last_verified", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fact_type", "key", name="uq_jarvis_facts_user_type_key"),
    )
    op.create_index("ix_jarvis_facts_user_type", "jarvis_facts", ["user_id", "fact_type"], unique=False)

    op.create_table(
        "jarvis_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_active",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "session_id", name="uq_jarvis_sessions_user_session"),
    )
    op.create_index("ix_jarvis_sessions_user_last", "jarvis_sessions", ["user_id", "last_active"], unique=False)

    op.create_table(
        "jarvis_session_turns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_row_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_row_id"], ["jarvis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jarvis_session_turns_session_created",
        "jarvis_session_turns",
        ["session_row_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jarvis_session_turns_session_created", table_name="jarvis_session_turns")
    op.drop_table("jarvis_session_turns")
    op.drop_index("ix_jarvis_sessions_user_last", table_name="jarvis_sessions")
    op.drop_table("jarvis_sessions")
    op.drop_index("ix_jarvis_facts_user_type", table_name="jarvis_facts")
    op.drop_table("jarvis_facts")
    op.drop_index(op.f("ix_jarvis_episodes_expires_at"), table_name="jarvis_episodes")
    op.drop_index("ix_jarvis_episodes_user_type", table_name="jarvis_episodes")
    op.drop_index("ix_jarvis_episodes_user_created", table_name="jarvis_episodes")
    op.drop_table("jarvis_episodes")
