"""Week 1: supporting indexes for research + personal expense time-range lists.

Revision ID: 0038_week1_query_indexes
Revises: 0037_part_e_generated_websites
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0038_week1_query_indexes"
down_revision: Union[str, Sequence[str], None] = "0037_part_e_generated_websites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_research_documents_org_created",
        "research_documents",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_govt_schemes_org_created",
        "govt_schemes",
        ["organization_id", "created_at"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_personal_expenses_user_spent",
        "personal_expenses",
        ["user_id", "spent_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_personal_expenses_user_spent", table_name="personal_expenses")
    op.drop_index("ix_govt_schemes_org_created", table_name="govt_schemes")
    op.drop_index("ix_research_documents_org_created", table_name="research_documents")
