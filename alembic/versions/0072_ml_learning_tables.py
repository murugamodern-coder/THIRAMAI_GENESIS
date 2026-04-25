"""Self-Evolution Phase 1: ML feedback loop tables.

Adds:
- ``learning_patterns`` (rolling pattern confidence)
- ``outcome_feedback`` (predicted vs actual)
- ``ml_models``       (model registry)
- ``evolution_triggers`` (self-coder proposal queue)

Revision ID: 0072_ml_learning_tables
Revises: 0071_security_audit_logs
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0072_ml_learning_tables"
down_revision: Union[str, Sequence[str], None] = "0071_security_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json_type(is_pg: bool) -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()


def _json_default(is_pg: bool):
    return sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = str(bind.dialect.name).lower() if bind is not None else "postgresql"
    is_pg = dialect == "postgresql"
    json_t = _json_type(is_pg)
    json_d = _json_default(is_pg)

    op.create_table(
        "learning_patterns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("pattern_type", sa.String(length=64), nullable=False),
        sa.Column("pattern_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_payload", json_t, nullable=False, server_default=json_d),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "pattern_type", "pattern_key", name="uq_learning_patterns_scope"
        ),
    )
    op.create_index(
        "ix_learning_patterns_organization_id",
        "learning_patterns",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_learning_patterns_pattern_type",
        "learning_patterns",
        ["pattern_type"],
        unique=False,
    )

    op.create_table(
        "outcome_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("action_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("action_type", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("predicted_outcome", json_t, nullable=False, server_default=json_d),
        sa.Column("actual_outcome", json_t, nullable=False, server_default=json_d),
        sa.Column("accuracy_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "learned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outcome_feedback_organization_id",
        "outcome_feedback",
        ["organization_id"],
        unique=False,
    )
    op.create_index("ix_outcome_feedback_user_id", "outcome_feedback", ["user_id"], unique=False)
    op.create_index(
        "ix_outcome_feedback_model_name", "outcome_feedback", ["model_name"], unique=False
    )
    op.create_index(
        "ix_outcome_feedback_action_id", "outcome_feedback", ["action_id"], unique=False
    )
    op.create_index(
        "ix_outcome_feedback_learned_at", "outcome_feedback", ["learned_at"], unique=False
    )

    op.create_table(
        "ml_models",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="0.0.1"),
        sa.Column("accuracy", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metrics", json_t, nullable=False, server_default=json_d),
        sa.Column("training_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "trained_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("model_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_ml_models_name_version"),
    )
    op.create_index("ix_ml_models_name", "ml_models", ["name"], unique=False)
    op.create_index("ix_ml_models_is_active", "ml_models", ["is_active"], unique=False)
    op.create_index("ix_ml_models_trained_at", "ml_models", ["trained_at"], unique=False)

    op.create_table(
        "evolution_triggers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("proposed_change", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="proposed"),
        sa.Column("evidence", json_t, nullable=False, server_default=json_d),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evolution_triggers_trigger_type",
        "evolution_triggers",
        ["trigger_type"],
        unique=False,
    )
    op.create_index(
        "ix_evolution_triggers_status", "evolution_triggers", ["status"], unique=False
    )
    op.create_index(
        "ix_evolution_triggers_created_at",
        "evolution_triggers",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_evolution_triggers_created_at", table_name="evolution_triggers")
    op.drop_index("ix_evolution_triggers_status", table_name="evolution_triggers")
    op.drop_index("ix_evolution_triggers_trigger_type", table_name="evolution_triggers")
    op.drop_table("evolution_triggers")

    op.drop_index("ix_ml_models_trained_at", table_name="ml_models")
    op.drop_index("ix_ml_models_is_active", table_name="ml_models")
    op.drop_index("ix_ml_models_name", table_name="ml_models")
    op.drop_table("ml_models")

    op.drop_index("ix_outcome_feedback_learned_at", table_name="outcome_feedback")
    op.drop_index("ix_outcome_feedback_action_id", table_name="outcome_feedback")
    op.drop_index("ix_outcome_feedback_model_name", table_name="outcome_feedback")
    op.drop_index("ix_outcome_feedback_user_id", table_name="outcome_feedback")
    op.drop_index("ix_outcome_feedback_organization_id", table_name="outcome_feedback")
    op.drop_table("outcome_feedback")

    op.drop_index("ix_learning_patterns_pattern_type", table_name="learning_patterns")
    op.drop_index("ix_learning_patterns_organization_id", table_name="learning_patterns")
    op.drop_table("learning_patterns")
