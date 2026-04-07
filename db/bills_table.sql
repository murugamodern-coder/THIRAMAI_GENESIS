-- Retail POS bills (line items JSON + total). Apply after db_schema.sql / ORM migrations.
-- psql "$DATABASE_URL" -f db/bills_table.sql

CREATE TABLE IF NOT EXISTS bills (
    id               BIGSERIAL PRIMARY KEY,
    organization_id  BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    items            JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_amount     NUMERIC(18, 2) NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_bills_organization_id ON bills (organization_id);
CREATE INDEX IF NOT EXISTS ix_bills_created_at ON bills (created_at DESC);
