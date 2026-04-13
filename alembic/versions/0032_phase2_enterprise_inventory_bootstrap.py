"""Ensure Phase 2 enterprise inventory tables exist (idempotent DDL).

Revision ID: 0032_phase2_enterprise_inventory_bootstrap
Revises: 0032_business_os_subsidy_tasks

``inventory_items`` and related objects live in ``db/phase2_core_business.sql`` but were not
part of the Alembic 0001 baseline tuple until fixed — databases that reached 0032 without that
file lack these tables, so 0033 (ALTER inventory_items, …) fails. This revision applies the
same idempotent SQL once so 0033+ can run safely.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from core.migration_sql import apply_sql_files

revision: str = "0032_phase2_enterprise_inventory_bootstrap"
down_revision: Union[str, Sequence[str], None] = "0032_business_os_subsidy_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    apply_sql_files(("db/phase2_core_business.sql",))


def downgrade() -> None:
    # Non-destructive bootstrap: do not drop tables (may contain data).
    pass
