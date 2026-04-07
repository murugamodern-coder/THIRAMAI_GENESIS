-- Phase 3 — AI decision engine persistence (PostgreSQL)
CREATE TABLE IF NOT EXISTS ai_decisions (
  id BIGSERIAL PRIMARY KEY,
  organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  action VARCHAR(64) NOT NULL,
  entity VARCHAR(64) NOT NULL DEFAULT '',
  priority VARCHAR(16) NOT NULL DEFAULT 'medium',
  requires_approval BOOLEAN NOT NULL DEFAULT TRUE,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  payload JSONB NOT NULL DEFAULT '{}',
  execution_result JSONB,
  error_message TEXT,
  correlation_id VARCHAR(128),
  resolved_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_ai_decisions_org ON ai_decisions(organization_id);
CREATE INDEX IF NOT EXISTS ix_ai_decisions_status ON ai_decisions(status);
CREATE INDEX IF NOT EXISTS ix_ai_decisions_action ON ai_decisions(action);
CREATE INDEX IF NOT EXISTS ix_ai_decisions_corr ON ai_decisions(correlation_id);
