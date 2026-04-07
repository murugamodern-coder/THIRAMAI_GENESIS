-- Invoice ledger (per-organization revenue). Apply on existing DBs:
--   psql "$DATABASE_URL" -f db/invoices.sql

CREATE TABLE IF NOT EXISTS invoices (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    invoice_no        TEXT NOT NULL DEFAULT '',
    invoice_date      DATE,
    grand_total_inr   NUMERIC(18, 2) NOT NULL DEFAULT 0,
    production_log_id BIGINT REFERENCES production_logs (id) ON DELETE SET NULL,
    external_ref      TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices (organization_id);
CREATE INDEX IF NOT EXISTS idx_invoices_created ON invoices (organization_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_org_external_ref
    ON invoices (organization_id, external_ref)
    WHERE external_ref IS NOT NULL AND btrim(external_ref) <> '';
