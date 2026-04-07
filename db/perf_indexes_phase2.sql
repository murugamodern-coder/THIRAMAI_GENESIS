-- Phase 2 / 3: performance indexes for high-traffic POS + billing paths.
-- Safe to re-run (IF NOT EXISTS). Apply after db_schema.sql and bills_table.sql.

-- Bills: time-ordered reports (already created in bills_table.sql as ix_bills_created_at)
CREATE INDEX IF NOT EXISTS ix_bills_created_at ON bills (created_at DESC);

-- Inventory: fast SKU lookup across tenants (partial index on name is optional)
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory (sku_name);

-- Composite for org-scoped stock lookups (supplements ux_inventory_org_sku_location)
CREATE INDEX IF NOT EXISTS ix_inventory_org_sku ON inventory (organization_id, sku_name);
