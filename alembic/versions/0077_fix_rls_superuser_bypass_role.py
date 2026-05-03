"""Recreate superuser_bypass RLS policies for the migration DB role (not hardcoded postgres).

Revision ID: 0077_fix_rls_superuser_bypass_role
Revises: 0076_paper_trading_table

Databases that applied 0047 when policies used TO postgres break when the cluster has no
postgres role (e.g. POSTGRES_USER=thiramai). Fresh 0047 uses session_user; this migration
repairs existing public.superuser_bypass policies to match the current connection role.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0077_fix_rls_superuser_bypass_role"
down_revision: Union[str, Sequence[str], None] = "0076_paper_trading_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    bypass_role = conn.execute(
        text("SELECT quote_ident(session_user::text)")
    ).scalar_one()
    rows = conn.execute(
        text(
            """
            SELECT c.relname
            FROM pg_policy p
            JOIN pg_class c ON c.oid = p.polrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE p.polname = 'superuser_bypass'
              AND n.nspname = 'public'
            ORDER BY c.relname
            """
        )
    ).fetchall()
    for row in rows:
        table = row[0]
        op.execute(f'DROP POLICY IF EXISTS superuser_bypass ON "{table}";')
        op.execute(
            f"""
            CREATE POLICY superuser_bypass ON "{table}"
            TO {bypass_role}
            USING (true);
            """
        )


def downgrade() -> None:
    """RLS role choice is environment-specific; no safe automatic revert."""
    pass
