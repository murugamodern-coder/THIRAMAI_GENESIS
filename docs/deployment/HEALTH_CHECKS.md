# Health check configuration

## Endpoints

### `GET /health/live`

**Purpose:** Liveness — process is running.

**Returns:** HTTP **200** with `{"status": "alive", ...}`.

Use for orchestration restart decisions (cheap probe).

### `GET /health/ready`

**Purpose:** Readiness — dependencies needed for traffic are usable.

**Returns:**

- HTTP **503** + `"status": "not_ready"` when a **critical** check fails (database, Redis when configured, Alembic head mismatch, optional workers, etc.).
- HTTP **200** + `"status": "ready"` when critical checks pass and there are no warnings, **or** critical passes with warnings while `THIRAMAI_HEALTH_STRICT_MODE=0`.
- HTTP **200** + `"status": "degraded"` when critical checks pass but there are **warnings** and `THIRAMAI_HEALTH_STRICT_MODE=1`.

Non-critical items are listed under `"warnings"` in the JSON body.

## Critical vs optional

| Check | Critical by default | Override |
| ----- | ------------------- | -------- |
| PostgreSQL `SELECT 1` | Yes | — |
| Connection pool not exhausted | Yes | — |
| Redis PING when `REDIS_URL` set | Yes | — |
| Alembic `version_num` vs expected head | Yes | `THIRAMAI_EXPECTED_DB_REVISION`, `THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=1` |
| Worker heartbeats when `THIRAMAI_HEALTH_EXPECT_WORKERS` set | Yes | Unset worker list |
| GROQ + TAVILY present | No | `THIRAMAI_HEALTH_REQUIRE_AI=1` to require |
| Goal-job SQLite ping | No | `THIRAMAI_HEALTH_REQUIRE_GOAL_SQLITE=1` to require, or `THIRAMAI_JOB_SQLITE=0` |
| PolicyEngine registry / circuit | Yes | `THIRAMAI_HEALTH_REQUIRE_POLICY_ENGINE=0` to disable |
| Execution failure rate / stuck runs | Yes (thresholds in code) | — |

Expected Alembic revision defaults to `core/migration_head.py` (`EXPECTED_ALEMBIC_REVISION`). Set `THIRAMAI_EXPECTED_DB_REVISION` when an image ships before/after the DB without updating that constant.

## Environment variables

```bash
# Optional: override baked-in expected Alembic head (must match alembic_version.version_num)
THIRAMAI_EXPECTED_DB_REVISION=0078_add_ai_decisions_table

# 1 = missing GROQ/TAVILY fails readiness
THIRAMAI_HEALTH_REQUIRE_AI=0

# 0 = do not require PolicyEngine to be healthy (emergency only)
THIRAMAI_HEALTH_REQUIRE_POLICY_ENGINE=1

# 1 = warnings produce status "degraded" (still HTTP 200)
THIRAMAI_HEALTH_STRICT_MODE=0

# 1 = revision mismatch is a warning only (avoid 503 when DB is ahead of image)
THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=0

# 1 = goal SQLite store must respond to ping
THIRAMAI_HEALTH_REQUIRE_GOAL_SQLITE=0

# Disable SQLite job queue (readonly volume / production without local SQLite)
THIRAMAI_JOB_SQLITE=0
# Alias read by thiramai/config.py:
# THIRAMAI_JOB_SQLITE_ENABLED=0
```

## Example payloads

**Healthy:**

```json
{
  "status": "ready",
  "checks": {
    "database": { "ok": true, "detail": "SELECT 1 ok" },
    "redis": { "ok": true, "detail": "PONG" },
    "alembic": { "ok": true, "detail": "at expected head", "revision": "0078_add_ai_decisions_table" },
    "ai": { "ok": false, "required_for_ready": false, "detail": "..." }
  },
  "warnings": ["AI: GROQ_API_KEY and/or TAVILY_API_KEY not set ..."]
}
```

**Strict mode with warnings:**

```json
{
  "status": "degraded",
  "warnings": ["AI: ..."],
  "checks": { }
}
```

See also [DATABASE_SETUP.md](DATABASE_SETUP.md) for migration / role notes.
