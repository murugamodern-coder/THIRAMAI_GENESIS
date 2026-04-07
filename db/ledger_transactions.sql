-- ERP journal (architecture doc: "transactions"). ORM: core.db.models.LedgerTransaction
-- Apply via Alembic revision 0011_ledger_transactions (preferred).

CREATE TABLE IF NOT EXISTS ledger_transactions (
    id BIGSERIAL PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    entry_type VARCHAR(32) NOT NULL DEFAULT 'adjustment',
    amount_inr NUMERIC(18, 2) NOT NULL,
    category VARCHAR(64) NOT NULL DEFAULT 'general',
    reference TEXT NOT NULL DEFAULT '',
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_ledger_transactions_organization_id ON ledger_transactions(organization_id);
CREATE INDEX IF NOT EXISTS ix_ledger_transactions_user_id ON ledger_transactions(user_id);
