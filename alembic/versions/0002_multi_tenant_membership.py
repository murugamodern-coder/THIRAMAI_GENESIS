"""Multi-tenant membership: ``user_organization_memberships``; drop ``users.organization_id`` / ``role_id``.

Revision ID: 0002_multi_tenant_membership
Revises: 0001
Create Date: 2026-03-30

PostgreSQL-oriented (matches baseline ``0001``). Migrates existing ``users`` rows into membership rows
before dropping the legacy columns.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_multi_tenant_membership"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_organization_memberships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_user_org_membership"),
    )
    op.create_index(
        "ix_user_organization_memberships_user_id",
        "user_organization_memberships",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_organization_memberships_organization_id",
        "user_organization_memberships",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_organization_memberships_role_id",
        "user_organization_memberships",
        ["role_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO user_organization_memberships (user_id, organization_id, role_id, is_active, joined_at)
            SELECT id, organization_id, role_id, is_active, created_at FROM users
            """
        )
    )

    op.drop_constraint("users_organization_id_fkey", "users", type_="foreignkey")
    op.drop_constraint("users_role_id_fkey", "users", type_="foreignkey")
    op.drop_index("ix_users_organization_id", table_name="users")
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_column("users", "organization_id")
    op.drop_column("users", "role_id")


def downgrade() -> None:
    raise NotImplementedError(
        "0002 downgrade is not implemented — restore from backup or add a forward migration."
    )
