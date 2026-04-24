"""enforce unique guardrail per user/rule/domain

Revision ID: 0068_guardrails_unique_user_rule_domain
Revises: 0067_real_world_autonomous_layer
Create Date: 2026-04-24 14:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0068_guardrails_unique_user_rule_domain"
down_revision = "0067_real_world_autonomous_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower()

    # Deduplicate existing rows first; keep the newest id.
    if dialect == "postgresql":
        op.execute(
            sa.text(
                """
                DELETE FROM guardrails g
                USING guardrails dup
                WHERE g.user_id = dup.user_id
                  AND g.rule_name = dup.rule_name
                  AND g.domain = dup.domain
                  AND g.id < dup.id
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                DELETE FROM guardrails
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM guardrails
                    GROUP BY user_id, rule_name, domain
                )
                """
            )
        )

    op.create_unique_constraint(
        "uq_guardrails_user_rule_domain",
        "guardrails",
        ["user_id", "rule_name", "domain"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_guardrails_user_rule_domain", "guardrails", type_="unique")

