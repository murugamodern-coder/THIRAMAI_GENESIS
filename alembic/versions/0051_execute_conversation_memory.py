"""Add execute conversation/message persistence tables.

Revision ID: 0051_execute_conversation_memory
Revises: 0050_rbac_role_permissions_and_user_role
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051_execute_conversation_memory"
down_revision: Union[str, Sequence[str], None] = "0050_rbac_role_permissions_and_user_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("conversations"):
        op.create_table(
            "conversations",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default="New conversation"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_conversations_user_id", "conversations", ["user_id"], unique=False)
        op.create_index(
            "ix_conversations_user_created",
            "conversations",
            ["user_id", "created_at"],
            unique=False,
        )

    if not insp.has_table("messages"):
        op.create_table(
            "messages",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "conversation_id",
                sa.BigInteger(),
                sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("role in ('user','assistant')", name="ck_messages_role"),
        )
        op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)
        op.create_index(
            "ix_messages_conversation_created",
            "messages",
            ["conversation_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("messages"):
        op.drop_index("ix_messages_conversation_created", table_name="messages", if_exists=True)
        op.drop_index("ix_messages_conversation_id", table_name="messages", if_exists=True)
        op.drop_table("messages")

    if insp.has_table("conversations"):
        op.drop_index("ix_conversations_user_created", table_name="conversations", if_exists=True)
        op.drop_index("ix_conversations_user_id", table_name="conversations", if_exists=True)
        op.drop_table("conversations")
