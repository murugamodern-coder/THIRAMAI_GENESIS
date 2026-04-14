"""Upgrade 2.3 — event queue for immediate Jarvis reactions (inventory, meetings, invoices).

Revision ID: 0042_jarvis_agent_event_queue
Revises: 0041_jarvis_autonomous_agent

PostgreSQL: optional NOTIFY-style durability via row inserts from triggers on core tables.
SQLite: table only; application hooks enqueue rows (triggers omitted for portability).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_jarvis_agent_event_queue"
down_revision: Union[str, Sequence[str], None] = "0041_jarvis_autonomous_agent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jarvis_agent_event_queue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jarvis_agent_event_queue_org_unprocessed",
        "jarvis_agent_event_queue",
        ["organization_id", "processed_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_jarvis_agent_event_queue_created",
        "jarvis_agent_event_queue",
        ["created_at"],
        unique=False,
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION jarvis_enqueue_inventory_qty()
            RETURNS TRIGGER AS $$
            DECLARE
              rp numeric;
            BEGIN
              rp := COALESCE(NEW.reorder_point, 0);
              IF TG_OP = 'UPDATE' AND (NEW.quantity IS DISTINCT FROM OLD.quantity) THEN
                INSERT INTO jarvis_agent_event_queue
                  (organization_id, user_id, event_type, payload, priority, created_at, processed_at)
                VALUES (
                  NEW.organization_id,
                  NULL,
                  'inventory_quantity_change',
                  jsonb_build_object(
                    'inventory_item_id', NEW.id,
                    'sku_name', NEW.sku_name,
                    'quantity', NEW.quantity::float,
                    'old_quantity', OLD.quantity::float,
                    'reorder_point', rp::float
                  ),
                  CASE WHEN NEW.quantity <= rp AND rp > 0 THEN 9 ELSE 4 END,
                  now(),
                  NULL
                );
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS jarvis_tr_inventory_qty ON inventory_items;"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER jarvis_tr_inventory_qty
            AFTER UPDATE OF quantity ON inventory_items
            FOR EACH ROW
            EXECUTE PROCEDURE jarvis_enqueue_inventory_qty();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION jarvis_enqueue_meeting_insert()
            RETURNS TRIGGER AS $$
            BEGIN
              INSERT INTO jarvis_agent_event_queue
                (organization_id, user_id, event_type, payload, priority, created_at, processed_at)
              VALUES (
                NEW.organization_id,
                NEW.user_id,
                'personal_meeting_created',
                jsonb_build_object(
                  'meeting_id', NEW.id,
                  'title', NEW.title,
                  'scheduled_at', NEW.scheduled_at
                ),
                6,
                now(),
                NULL
              );
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS jarvis_tr_meeting_ins ON personal_meetings;"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER jarvis_tr_meeting_ins
            AFTER INSERT ON personal_meetings
            FOR EACH ROW
            EXECUTE PROCEDURE jarvis_enqueue_meeting_insert();
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION jarvis_enqueue_invoice_insert()
            RETURNS TRIGGER AS $$
            BEGIN
              INSERT INTO jarvis_agent_event_queue
                (organization_id, user_id, event_type, payload, priority, created_at, processed_at)
              VALUES (
                NEW.organization_id,
                NULL,
                'invoice_created',
                jsonb_build_object(
                  'invoice_id', NEW.id,
                  'invoice_no', NEW.invoice_no,
                  'grand_total_inr', NEW.grand_total_inr::float,
                  'payment_status', NEW.payment_status
                ),
                5,
                now(),
                NULL
              );
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS jarvis_tr_invoice_ins ON invoices;"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER jarvis_tr_invoice_ins
            AFTER INSERT ON invoices
            FOR EACH ROW
            EXECUTE PROCEDURE jarvis_enqueue_invoice_insert();
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP TRIGGER IF EXISTS jarvis_tr_invoice_ins ON invoices;"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS jarvis_enqueue_invoice_insert();"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS jarvis_tr_meeting_ins ON personal_meetings;"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS jarvis_enqueue_meeting_insert();"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS jarvis_tr_inventory_qty ON inventory_items;"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS jarvis_enqueue_inventory_qty();"))
    op.drop_index("ix_jarvis_agent_event_queue_created", table_name="jarvis_agent_event_queue")
    op.drop_index("ix_jarvis_agent_event_queue_org_unprocessed", table_name="jarvis_agent_event_queue")
    op.drop_table("jarvis_agent_event_queue")
