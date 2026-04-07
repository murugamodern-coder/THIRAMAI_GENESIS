-- Life OS (Personal Core): per-user planner, health logs, reminders + optional vault crypto.
-- Apply after auth/users exist: psql "$DATABASE_URL" -f db/life_os.sql

CREATE TABLE IF NOT EXISTS user_personal_crypto (
    user_id            BIGINT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    salt               BYTEA NOT NULL,
    key_verifier_hash  TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_planner (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    for_date           DATE NOT NULL,
    blocks             JSONB NOT NULL DEFAULT '[]',
    private_notes_cipher BYTEA,
    ai_flow_hint       TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_daily_planner_user_date UNIQUE (user_id, for_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_planner_user ON daily_planner (user_id, for_date DESC);

CREATE TABLE IF NOT EXISTS health_logs (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    logged_on          DATE NOT NULL,
    sleep_hours        NUMERIC(4, 2),
    water_glasses      INTEGER,
    stress_1_10        INTEGER,
    reflection_cipher  BYTEA,
    reflection_encrypted BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_health_logs_user_day UNIQUE (user_id, logged_on)
);

CREATE INDEX IF NOT EXISTS idx_health_logs_user ON health_logs (user_id, logged_on DESC);

CREATE TABLE IF NOT EXISTS personal_reminders (
    id                 BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    remind_at          TIMESTAMPTZ NOT NULL,
    title              TEXT NOT NULL DEFAULT '',
    body_cipher        BYTEA,
    body_encrypted     BOOLEAN NOT NULL DEFAULT false,
    done_at            TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_personal_reminders_user_due ON personal_reminders (user_id, remind_at);
