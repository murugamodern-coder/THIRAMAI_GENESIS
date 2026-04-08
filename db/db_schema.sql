-- THIRAMAI V2.1 relational schema (organizations, assets, debts, inventory, production_logs)
-- Apply: psql "$DATABASE_URL" -f db/db_schema.sql
-- SQLAlchemy models: core/db/models.py — engine/session: core/database.py

CREATE TYPE asset_status_enum AS ENUM ('active', 'archived', 'pending');

CREATE TYPE debt_category_enum AS ENUM (
    'term_loan',
    'working_capital',
    'credit_card',
    'payable',
    'other'
);

CREATE TABLE organizations (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    gst_number   TEXT,
    industry     TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_organizations_display_name UNIQUE (name)
);

CREATE UNIQUE INDEX uq_organizations_gst_number
    ON organizations (gst_number)
    WHERE gst_number IS NOT NULL AND btrim(gst_number) <> '';

CREATE TABLE assets (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    category          TEXT NOT NULL,
    valuation         NUMERIC(18, 2),
    status_enum       asset_status_enum NOT NULL DEFAULT 'active',
    external_ref      TEXT
);

CREATE UNIQUE INDEX ux_assets_org_external_ref
    ON assets (organization_id, external_ref)
    WHERE external_ref IS NOT NULL AND btrim(external_ref) <> '';

CREATE INDEX idx_assets_org ON assets (organization_id);
CREATE INDEX idx_assets_category ON assets (category);

CREATE TABLE debts (
    id                      BIGSERIAL PRIMARY KEY,
    organization_id         BIGINT REFERENCES organizations (id) ON DELETE SET NULL,
    lender_name             TEXT NOT NULL,
    principal               NUMERIC(18, 2) NOT NULL DEFAULT 0,
    interest_rate           NUMERIC(8, 4),
    start_date              DATE,
    due_date                DATE,
    category_enum           debt_category_enum NOT NULL DEFAULT 'other',
    external_ref            TEXT
);

CREATE UNIQUE INDEX ux_debts_external_ref
    ON debts (external_ref)
    WHERE external_ref IS NOT NULL AND btrim(external_ref) <> '';

CREATE INDEX idx_debts_org ON debts (organization_id);

CREATE TABLE inventory (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT REFERENCES organizations (id) ON DELETE SET NULL,
    sku_name          TEXT NOT NULL,
    quantity          NUMERIC(18, 4) NOT NULL DEFAULT 0,
    location          TEXT NOT NULL DEFAULT '',
    unit_price        NUMERIC(18, 2),
    total_value       NUMERIC(18, 2),
    gst_rate_percent  NUMERIC(5, 2),
    hsn_code          TEXT,
    external_ref      TEXT
);

CREATE UNIQUE INDEX ux_inventory_org_sku_location
    ON inventory (organization_id, sku_name, location)
    WHERE organization_id IS NOT NULL;

CREATE INDEX idx_inventory_sku ON inventory (sku_name);

CREATE TABLE production_logs (
    id                BIGSERIAL PRIMARY KEY,
    asset_id          BIGINT NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
    timestamp         TIMESTAMPTZ NOT NULL DEFAULT now(),
    production_unit   TEXT NOT NULL DEFAULT 'general',
    cement_in         NUMERIC(18, 4),
    sand_in           NUMERIC(18, 4),
    blocks_out        NUMERIC(18, 4),
    raw_material_in   NUMERIC(18, 4),
    yield_out         NUMERIC(18, 4),
    labor_cost        NUMERIC(18, 2),
    external_ref      TEXT
);

CREATE UNIQUE INDEX ux_production_logs_asset_external_ref
    ON production_logs (asset_id, external_ref)
    WHERE external_ref IS NOT NULL AND btrim(external_ref) <> '';

CREATE INDEX idx_production_logs_asset ON production_logs (asset_id);
CREATE INDEX idx_production_logs_ts ON production_logs (timestamp DESC);

CREATE TABLE departments (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_departments_org_name UNIQUE (organization_id, name)
);

CREATE INDEX idx_departments_org ON departments (organization_id);

CREATE TABLE invoices (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    invoice_no        TEXT NOT NULL DEFAULT '',
    invoice_date      DATE,
    grand_total_inr   NUMERIC(18, 2) NOT NULL DEFAULT 0,
    production_log_id BIGINT REFERENCES production_logs (id) ON DELETE SET NULL,
    external_ref      TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_invoices_org ON invoices (organization_id);
CREATE INDEX idx_invoices_created ON invoices (organization_id, created_at DESC);

CREATE UNIQUE INDEX ux_invoices_org_external_ref
    ON invoices (organization_id, external_ref)
    WHERE external_ref IS NOT NULL AND btrim(external_ref) <> '';

-- In-app alerts (workers/alert_system.py); existing DBs: db/notifications_alerts.sql
CREATE TABLE notifications (
    id                BIGSERIAL PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
    kind              VARCHAR(64) NOT NULL,
    severity          VARCHAR(16) NOT NULL DEFAULT 'warning',
    title             TEXT NOT NULL,
    body              TEXT NOT NULL,
    reference_type    VARCHAR(64),
    reference_id      BIGINT,
    payload           JSONB NOT NULL DEFAULT '{}',
    dedupe_key        VARCHAR(256) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at           TIMESTAMPTZ,
    CONSTRAINT uq_notifications_org_dedupe UNIQUE (organization_id, dedupe_key)
);

CREATE INDEX idx_notifications_org_created ON notifications (organization_id, created_at DESC);
CREATE INDEX idx_notifications_kind ON notifications (kind);

-- Idempotency + job queue (workers/run_worker.py, workers/idempotency.py); see db/idempotency_and_jobs.sql
CREATE TABLE idempotency_keys (
    idempotency_key VARCHAR(512) PRIMARY KEY,
    action_type     VARCHAR(128) NOT NULL DEFAULT '',
    meta            JSONB NOT NULL DEFAULT '{}',
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_idempotency_keys_completed
    ON idempotency_keys (completed_at)
    WHERE completed_at IS NOT NULL;

CREATE INDEX idx_idempotency_keys_created_pending
    ON idempotency_keys (created_at)
    WHERE completed_at IS NULL;

CREATE TABLE background_jobs (
    id                BIGSERIAL PRIMARY KEY,
    job_type          VARCHAR(64) NOT NULL,
    organization_id   BIGINT REFERENCES organizations (id) ON DELETE CASCADE,
    idempotency_key   VARCHAR(512) NOT NULL,
    payload           JSONB NOT NULL DEFAULT '{}',
    status            VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts          INTEGER NOT NULL DEFAULT 0,
    max_attempts      INTEGER NOT NULL DEFAULT 5,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ
);

CREATE INDEX idx_background_jobs_pending ON background_jobs (status, id) WHERE status = 'pending';
CREATE INDEX idx_background_jobs_org_created ON background_jobs (organization_id, created_at DESC);

-- Tables that reference `users` (Life OS crypto/planner/health/reminders; Factory OS staff assignments)
-- MUST NOT appear in this file: `users` is created in db/auth_rbac.sql after this script.
-- Applied later by Alembic baseline order in core/migration_sql.py:
--   db/auth_rbac.sql  → users, roles, permissions
--   …
--   db/factory_os.sql → factory_billing_hold, project_stages, project_staff_assignments (IF NOT EXISTS)
--   db/life_os.sql    → user_personal_crypto, daily_planner, health_logs, personal_reminders (IF NOT EXISTS)
