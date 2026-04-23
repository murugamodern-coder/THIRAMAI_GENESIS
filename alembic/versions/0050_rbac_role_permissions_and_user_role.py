"""Add extensible RBAC mappings and user role linkage.

Revision ID: 0050_rbac_role_permissions_and_user_role
Revises: 0049_merge_correlation_id
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050_rbac_role_permissions_and_user_role"
down_revision: Union[str, Sequence[str], None] = "0049_merge_correlation_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp: sa.Inspector, table: str, column: str) -> bool:
    if not insp.has_table(table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("users") and not _has_column(insp, "users", "name"):
        op.add_column("users", sa.Column("name", sa.String(length=160), nullable=False, server_default=""))

    if insp.has_table("users") and not _has_column(insp, "users", "role_id"):
        op.add_column("users", sa.Column("role_id", sa.BigInteger(), nullable=True))
        op.create_foreign_key(
            "fk_users_role_id_roles",
            "users",
            "roles",
            ["role_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_users_role_id", "users", ["role_id"], unique=False)

    if insp.has_table("permissions") and not _has_column(insp, "permissions", "name"):
        op.add_column("permissions", sa.Column("name", sa.String(length=128), nullable=True))
        op.execute(sa.text("UPDATE permissions SET name = COALESCE(name, resource || ':' || action)"))
        op.alter_column("permissions", "name", existing_type=sa.String(length=128), nullable=False)
        op.create_index("ix_permissions_name", "permissions", ["name"], unique=True)

    if not insp.has_table("role_permissions"):
        op.create_table(
            "role_permissions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("role_id", sa.BigInteger(), nullable=False),
            sa.Column("permission_id", sa.BigInteger(), nullable=False),
            sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_role_permission"),
        )
        op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"], unique=False)
        op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"], unique=False)

    if insp.has_table("roles"):
        # Seed baseline role catalog across existing organizations.
        op.execute(
            sa.text(
                """
                INSERT INTO roles (org_id, name, level)
                SELECT o.id, v.name, v.level
                FROM organizations o
                CROSS JOIN (VALUES
                    ('owner', 100),
                    ('admin', 80),
                    ('staff', 40),
                    ('family', 20)
                ) AS v(name, level)
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM roles r
                    WHERE r.org_id = o.id AND LOWER(r.name) = LOWER(v.name)
                )
                """
            )
        )

    if insp.has_table("permissions") and insp.has_table("role_permissions"):
        # Backfill m2m mapping from legacy permissions.role_id relation.
        op.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT p.role_id, p.id
                FROM permissions p
                WHERE p.role_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM role_permissions rp
                    WHERE rp.role_id = p.role_id AND rp.permission_id = p.id
                )
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("role_permissions"):
        op.drop_index("ix_role_permissions_permission_id", table_name="role_permissions", if_exists=True)
        op.drop_index("ix_role_permissions_role_id", table_name="role_permissions", if_exists=True)
        op.drop_table("role_permissions")

    if insp.has_table("permissions") and _has_column(insp, "permissions", "name"):
        op.drop_index("ix_permissions_name", table_name="permissions", if_exists=True)
        op.drop_column("permissions", "name")

    if insp.has_table("users") and _has_column(insp, "users", "role_id"):
        op.drop_index("ix_users_role_id", table_name="users", if_exists=True)
        op.drop_constraint("fk_users_role_id_roles", "users", type_="foreignkey")
        op.drop_column("users", "role_id")

    if insp.has_table("users") and _has_column(insp, "users", "name"):
        op.drop_column("users", "name")
