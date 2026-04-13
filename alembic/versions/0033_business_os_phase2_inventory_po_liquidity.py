"""Business OS Phase 2: unit/lot on stock, subsidy fields, e-way on invoices, PO supplier ref, supplier payments, liquidity.

Revision ID: 0033_business_os_phase2_inventory_po_liquidity
Revises: 0032_phase2_enterprise_inventory_bootstrap
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_business_os_phase2_inventory_po_liquidity"
down_revision: Union[str, Sequence[str], None] = "0032_phase2_enterprise_inventory_bootstrap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory_items", sa.Column("unit", sa.String(length=32), nullable=False, server_default=""))
    op.alter_column("inventory_items", "unit", server_default=None)

    op.add_column("stock_movements", sa.Column("lot_batch", sa.String(length=64), nullable=True))
    op.add_column("stock_movements", sa.Column("reason", sa.String(length=256), nullable=True))

    op.add_column("agro_subsidy_cases", sa.Column("farmer_phone", sa.String(length=32), nullable=True))
    op.add_column(
        "agro_subsidy_cases",
        sa.Column("land_acres", sa.Numeric(precision=14, scale=4), nullable=True),
    )
    op.add_column(
        "agro_subsidy_cases",
        sa.Column("subsidy_applied_inr", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
    )
    op.add_column(
        "agro_subsidy_cases",
        sa.Column("subsidy_approved_inr", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
    )
    op.add_column(
        "agro_subsidy_cases",
        sa.Column("commission_earned_inr", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
    )
    op.alter_column("agro_subsidy_cases", "subsidy_applied_inr", server_default=None)
    op.alter_column("agro_subsidy_cases", "subsidy_approved_inr", server_default=None)
    op.alter_column("agro_subsidy_cases", "commission_earned_inr", server_default=None)

    op.add_column("invoices", sa.Column("eway_bill_no", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("vehicle_no", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("transport_mode", sa.String(length=32), nullable=True))
    op.add_column("invoices", sa.Column("consignee_place", sa.Text(), nullable=True))

    op.add_column("purchase_orders", sa.Column("supplier_invoice_no", sa.Text(), nullable=True))
    op.add_column("purchase_orders", sa.Column("supplier_invoice_date", sa.Date(), nullable=True))

    op.create_table(
        "supplier_payments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), nullable=True),
        sa.Column("amount_inr", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False, server_default="bank"),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "paid_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_supplier_payments_org", "supplier_payments", ["organization_id"])
    op.create_index("ix_supplier_payments_supplier", "supplier_payments", ["supplier_id"])

    op.create_table(
        "organization_liquidity",
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("cash_inr", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
        sa.Column("bank_inr", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id"),
    )


def downgrade() -> None:
    op.drop_table("organization_liquidity")
    op.drop_index("ix_supplier_payments_supplier", table_name="supplier_payments")
    op.drop_index("ix_supplier_payments_org", table_name="supplier_payments")
    op.drop_table("supplier_payments")
    op.drop_column("purchase_orders", "supplier_invoice_date")
    op.drop_column("purchase_orders", "supplier_invoice_no")
    op.drop_column("invoices", "consignee_place")
    op.drop_column("invoices", "transport_mode")
    op.drop_column("invoices", "vehicle_no")
    op.drop_column("invoices", "eway_bill_no")
    op.drop_column("agro_subsidy_cases", "commission_earned_inr")
    op.drop_column("agro_subsidy_cases", "subsidy_approved_inr")
    op.drop_column("agro_subsidy_cases", "subsidy_applied_inr")
    op.drop_column("agro_subsidy_cases", "land_acres")
    op.drop_column("agro_subsidy_cases", "farmer_phone")
    op.drop_column("stock_movements", "reason")
    op.drop_column("stock_movements", "lot_batch")
    op.drop_column("inventory_items", "unit")
