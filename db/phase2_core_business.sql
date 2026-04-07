-- Phase 2 — core business tables (PostgreSQL). Apply after baseline schema.
-- Idempotent patterns: use IF NOT EXISTS where supported.

-- Legacy invoices: lifecycle columns (ORM also defines defaults for new installs)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'posted';
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_status VARCHAR(32) NOT NULL DEFAULT 'unpaid';

CREATE TABLE IF NOT EXISTS inventory_items (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  sku_name TEXT NOT NULL,
  quantity NUMERIC(18,4) NOT NULL DEFAULT 0,
  location TEXT NOT NULL DEFAULT '',
  unit_price NUMERIC(18,2),
  unit_cost_pre_tax NUMERIC(18,2),
  total_value NUMERIC(18,2),
  gst_rate_percent NUMERIC(5,2),
  hsn_code TEXT,
  external_ref TEXT,
  reorder_point NUMERIC(18,4),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_inventory_items_org_sku_loc UNIQUE (organization_id, sku_name, location)
);
CREATE INDEX IF NOT EXISTS ix_inventory_items_org ON inventory_items(organization_id);

CREATE TABLE IF NOT EXISTS stock_movements (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  inventory_item_id BIGINT NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
  quantity_delta NUMERIC(18,4) NOT NULL,
  movement_type VARCHAR(32) NOT NULL DEFAULT 'ADJUST',
  reference_type VARCHAR(64),
  reference_id VARCHAR(128),
  notes TEXT,
  created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_stock_movements_org ON stock_movements(organization_id);
CREATE INDEX IF NOT EXISTS ix_stock_movements_item ON stock_movements(inventory_item_id);

CREATE TABLE IF NOT EXISTS suppliers (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  gstin VARCHAR(15),
  contact_email TEXT,
  phone VARCHAR(32),
  address TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_suppliers_org ON suppliers(organization_id);

CREATE TABLE IF NOT EXISTS purchase_orders (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  supplier_id BIGINT NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  order_date DATE NOT NULL,
  expected_date DATE,
  notes TEXT,
  total_inr NUMERIC(18,2) NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_po_org ON purchase_orders(organization_id);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
  id BIGSERIAL PRIMARY KEY,
  purchase_order_id BIGINT NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
  sku_name TEXT NOT NULL,
  quantity_ordered NUMERIC(18,4) NOT NULL,
  quantity_received NUMERIC(18,4) NOT NULL DEFAULT 0,
  unit_cost_pre_tax NUMERIC(18,4) NOT NULL,
  line_total_inr NUMERIC(18,2) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_pol_po ON purchase_order_lines(purchase_order_id);

CREATE TABLE IF NOT EXISTS invoice_items (
  id BIGSERIAL PRIMARY KEY,
  invoice_id BIGINT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  line_no INT NOT NULL DEFAULT 1,
  description TEXT NOT NULL DEFAULT '',
  quantity NUMERIC(18,4) NOT NULL DEFAULT 1,
  unit_price_pre_tax NUMERIC(18,4) NOT NULL,
  gst_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
  line_total_inr NUMERIC(18,2) NOT NULL,
  hsn_code VARCHAR(16)
);
CREATE INDEX IF NOT EXISTS ix_invoice_items_inv ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS payments (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  invoice_id BIGINT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  amount_inr NUMERIC(18,2) NOT NULL,
  method VARCHAR(32) NOT NULL DEFAULT 'bank',
  reference TEXT,
  paid_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_payments_org ON payments(organization_id);
CREATE INDEX IF NOT EXISTS ix_payments_inv ON payments(invoice_id);

CREATE TABLE IF NOT EXISTS gst_records (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  period_start DATE NOT NULL,
  data JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_gst_org_period UNIQUE (organization_id, period_start)
);
CREATE INDEX IF NOT EXISTS ix_gst_org ON gst_records(organization_id);

CREATE TABLE IF NOT EXISTS raw_materials (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  unit VARCHAR(32) NOT NULL DEFAULT 'kg',
  quantity_on_hand NUMERIC(18,4) NOT NULL DEFAULT 0,
  reorder_point NUMERIC(18,4),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_raw_org ON raw_materials(organization_id);
