"""Add ai_decisions table for Phase 3 decision persistence.

Matches ``core.db.models.AiDecision`` (payload JSONB, RLS on ``organization_id``).

Revision ID: 0078_add_ai_decisions_table
Revises: 0077_fix_rls_superuser_bypass_role
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision: str = "0078_add_ai_decisions_table"
down_revision: Union[str, Sequence[str], None] = "0077_fix_rls_superuser_bypass_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type(is_pg: bool) -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def _json_default(is_pg: bool):
    return sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")


def _session_role_ident() -> str:
    return op.get_bind().execute(text("SELECT quote_ident(session_user::text)")).scalar_one()


def _enable_rls_ai_decisions(bypass_role: str) -> None:
    op.execute('ALTER TABLE "ai_decisions" ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE "ai_decisions" FORCE ROW LEVEL SECURITY;')
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "ai_decisions";')
    op.execute('DROP POLICY IF EXISTS superuser_bypass ON "ai_decisions";')
    op.execute(
        """
        CREATE POLICY tenant_isolation ON "ai_decisions"
        USING (
            "organization_id" = current_setting('app.current_org_id', true)::bigint
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY superuser_bypass ON "ai_decisions"
        TO {bypass_role}
        USING (true);
        """
    )


def _disable_rls_ai_decisions() -> None:
    present = op.get_bind().execute(
        text("SELECT to_regclass('public.ai_decisions') IS NOT NULL")
    ).scalar_one()
    if not present:
        return
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "ai_decisions";')
    op.execute('DROP POLICY IF EXISTS superuser_bypass ON "ai_decisions";')
    op.execute('ALTER TABLE "ai_decisions" DISABLE ROW LEVEL SECURITY;')


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    is_pg = dialect == "postgresql"
    json_t = _json_type(is_pg)
    json_d = _json_default(is_pg)

    exists = bool(
        bind.execute(
            text("SELECT to_regclass('public.ai_decisions') IS NOT NULL")
        ).scalar_one()
    )

    if exists:
        # Table already present (manual / partial deploy); still align RLS with 0047-style tenant isolation.
        if is_pg:
            bypass_role = _session_role_ident()
            _enable_rls_ai_decisions(bypass_role)
        return

    op.create_table(
        "ai_decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("payload", json_t, nullable=False, server_default=json_d),
        sa.Column("execution_result", json_t, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("resolved_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_decisions_organization_id",
        "ai_decisions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_decisions_user_id",
        "ai_decisions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_decisions_action",
        "ai_decisions",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_ai_decisions_status",
        "ai_decisions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_ai_decisions_correlation_id",
        "ai_decisions",
        ["correlation_id"],
        unique=False,
    )

    if is_pg:
        bypass_role = _session_role_ident()
        _enable_rls_ai_decisions(bypass_role)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    is_pg = dialect == "postgresql"

    if is_pg:
        _disable_rls_ai_decisions()

    op.drop_index("ix_ai_decisions_correlation_id", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_status", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_action", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_user_id", table_name="ai_decisions")
    op.drop_index("ix_ai_decisions_organization_id", table_name="ai_decisions")
    op.drop_table("ai_decisions")
