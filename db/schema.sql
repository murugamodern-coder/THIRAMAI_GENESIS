-- Legacy reference — **use db/db_schema.sql** for THIRAMAI V2.1 (`organizations` + extended columns).
-- THIRAMAI PostgreSQL schema v1 (orgs, assets, debts, inventory, production_logs)
-- Apply: psql "$DATABASE_URL" -f db/schema.sql

CREATE TYPE asset_status_enum AS ENUM ('active', 'archived', 'pending');

CREATE TYPE debt_category_enum AS ENUM (
    'term_loan',
    'working_capital',
    'credit_card',
    'payable',
    'other'
);

CREATE TABLE orgs (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    gst_number  TEXT,
    industry    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE assets (
    id            BIGSERIAL PRIMARY KEY,
    org_id        BIGINT NOT NULL REFERENCES orgs (id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    valuation     NUMERIC(18, 2),
    status_enum   asset_status_enum NOT NULL DEFAULT 'active'
);

CREATE INDEX idx_assets_org ON assets (org_id);
CREATE INDEX idx_assets_category ON assets (category);

CREATE TABLE debts (
    id             BIGSERIAL PRIMARY KEY,
    lender_name    TEXT NOT NULL,
    principal      NUMERIC(18, 2) NOT NULL DEFAULT 0,
    interest_rate  NUMERIC(8, 4),
    start_date     DATE,
    category_enum  debt_category_enum NOT NULL DEFAULT 'other'
);

CREATE TABLE inventory (
    id           BIGSERIAL PRIMARY KEY,
    sku_name     TEXT NOT NULL,
    quantity     NUMERIC(18, 4) NOT NULL DEFAULT 0,
    unit_price   NUMERIC(18, 2),
    total_value  NUMERIC(18, 2)
);

CREATE INDEX idx_inventory_sku ON inventory (sku_name);

CREATE TABLE production_logs (
    id               BIGSERIAL PRIMARY KEY,
    asset_id         BIGINT NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_material_in  NUMERIC(18, 4),
    yield_out        NUMERIC(18, 4),
    labor_cost       NUMERIC(18, 2)
);

CREATE INDEX idx_production_logs_asset ON production_logs (asset_id);
CREATE INDEX idx_production_logs_ts ON production_logs (timestamp DESC);
