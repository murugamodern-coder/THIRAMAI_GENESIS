"""Fix learning_logs user_id type consistency and add constraints

Revision ID: 0069_fix_learning_logs_user_id_integrity
Revises: 0068_guardrails_unique_user_rule_domain
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0069_fix_learning_logs_user_id_integrity"
down_revision: Union[str, Sequence[str], None] = "0068_guardrails_unique_user_rule_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(insp, table: str, column: str) -> bool:
    try:
        return any(c.get("name") == column for c in insp.get_columns(table))
    except Exception:
        return False


def _has_index(insp, table: str, name: str) -> bool:
    try:
        for ix in insp.get_indexes(table):
            if str(ix.get("name")) == name:
                return True
    except Exception:
        pass
    return False


def _pg_user_id_udt(conn) -> str:
    r = conn.execute(
        sa.text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='learning_logs' AND column_name='user_id'"
        )
    ).fetchone()
    return str((r[0] or "")).lower() if r and r[0] else ""


def _pg_has_fk(insp, name: str) -> bool:
    for fk in insp.get_foreign_keys("learning_logs") or []:
        if (fk.get("name") or "") == name:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    insp = sa.inspect(bind)
    if not insp.has_table("learning_logs"):
        return
    dialect = str(bind.dialect.name).lower()

    if not _has_column(insp, "learning_logs", "resolved_by_user_id"):
        op.add_column(
            "learning_logs",
            sa.Column("resolved_by_user_id", sa.BigInteger(), nullable=True),
        )
        if dialect == "postgresql":
            op.create_foreign_key(
                "fk_learning_logs_resolved_by_user_id_users",
                "learning_logs",
                "users",
                ["resolved_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
    insp = sa.inspect(bind)

    if dialect == "postgresql":
        udt = _pg_user_id_udt(bind)
        if udt in ("int8", "int4", "int2"):
            if not _pg_has_fk(insp, "fk_learning_logs_user_id_users"):
                op.create_foreign_key(
                    "fk_learning_logs_user_id_users",
                    "learning_logs",
                    "users",
                    ["user_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        elif udt:
            op.execute(sa.text("ALTER TABLE learning_logs DROP CONSTRAINT IF EXISTS fk_learning_logs_user_id_users"))
            if udt == "uuid":
                op.execute(
                    sa.text(
                        "ALTER TABLE learning_logs ALTER COLUMN user_id TYPE bigint "
                        "USING (resolved_by_user_id)"
                    )
                )
            else:
                op.execute(
                    sa.text(
                        "ALTER TABLE learning_logs ALTER COLUMN user_id TYPE bigint "
                        "USING ("
                        "  CASE"
                        "    WHEN user_id IS NULL THEN NULL::bigint"
                        "    WHEN user_id::text ~ '^[0-9]+$' THEN trim(user_id::text)::bigint"
                        "    ELSE resolved_by_user_id"
                        "  END"
                        ")"
                    )
                )
            op.create_foreign_key(
                "fk_learning_logs_user_id_users",
                "learning_logs",
                "users",
                ["user_id"],
                ["id"],
                ondelete="SET NULL",
            )
        insp = sa.inspect(bind)

    if _has_column(insp, "learning_logs", "resolved_by_user_id") and not _has_index(
        insp, "learning_logs", "idx_learning_logs_resolved_by"
    ):
        op.create_index(
            "idx_learning_logs_resolved_by",
            "learning_logs",
            ["resolved_by_user_id"],
            unique=False,
            if_not_exists=True,
            postgresql_using="btree" if dialect == "postgresql" else None,
        )

    insp = sa.inspect(bind)
    if not _has_index(insp, "learning_logs", "ix_learning_logs_org_created") and not _has_index(
        insp, "learning_logs", "idx_learning_logs_user_org"
    ):
        op.create_index(
            "idx_learning_logs_user_org",
            "learning_logs",
            ["organization_id", "created_at"],
            unique=False,
            if_not_exists=True,
            postgresql_using="btree" if dialect == "postgresql" else None,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind is None:
        return
    insp = sa.inspect(bind)
    if not insp.has_table("learning_logs"):
        return
    if _has_index(insp, "learning_logs", "idx_learning_logs_resolved_by"):
        op.drop_index("idx_learning_logs_resolved_by", table_name="learning_logs", if_exists=True)
    if _has_index(insp, "learning_logs", "idx_learning_logs_user_org"):
        op.drop_index("idx_learning_logs_user_org", table_name="learning_logs", if_exists=True)
