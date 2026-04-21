"""Per-user runtime config (broker keys, feature toggles) for vault_service.

Revision ID: 0048_user_runtime_config
Revises: 0047_add_rls_tenant_isolation
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0048_user_runtime_config"
down_revision: Union[str, Sequence[str], None] = "0047_add_rls_tenant_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_runtime_config",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("config_key", sa.String(length=128), nullable=False),
        sa.Column("config_value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "config_key"),
    )
    op.create_index(
        "ix_user_runtime_config_updated_at",
        "user_runtime_config",
        ["updated_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_user_runtime_config_updated_at", table_name="user_runtime_config", if_exists=True)
    op.drop_table("user_runtime_config")
