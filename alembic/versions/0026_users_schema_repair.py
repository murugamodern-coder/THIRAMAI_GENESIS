"""Repair incomplete ``users`` table (role_id, organization_id, timestamps, FKs).

Revision ID: 0026_users_schema_repair
Revises: 0025_autonomy_settings_and_feedback
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0026_users_schema_repair"
down_revision: Union[str, Sequence[str], None] = "0025_autonomy_settings_and_feedback"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "db" / "users_schema_repair.sql"
    sql_script = path.read_text(encoding="utf-8")
    bind = op.get_bind()
    raw = bind.connection.dbapi_connection
    with raw.cursor() as cur:
        cur.execute(sql_script)


def downgrade() -> None:
    raise NotImplementedError("users_schema_repair downgrade is not supported.")
