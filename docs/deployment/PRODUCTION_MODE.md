# Production Mode

## Clean Production State

Run the stack with **Alembic validation enabled** and **`THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH`** so revision drift is surfaced as warnings instead of failing readiness (when the DB and expected revision differ by policy).

### Configuration

```bash
# .env.production

# ✅ PROPER MODE (Current)
THIRAMAI_SKIP_ALEMBIC_CHECK=0                    # Check enabled
THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=1        # Mismatch OK (warning, not 503)
THIRAMAI_EXPECTED_DB_REVISION=0078_add_ai_decisions_table

# ❌ HACK MODE (Previous - Don't use)
THIRAMAI_SKIP_ALEMBIC_CHECK=1                    # Skip = bypass Alembic entirely
```

### Why This Matters

**Skip Mode (Temporary):**

- Bypasses the Alembic version check entirely.
- Useful only when the running image did not yet support env-based expected revision / ignore mismatch.

**Ignore Mismatch Mode (Preferred):**

- Connects to PostgreSQL and reads `alembic_version`.
- Compares to `THIRAMAI_EXPECTED_DB_REVISION` (or repo head from `core/migration_head.py` when unset).
- When `THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=1`, a mismatch stays **`checks.alembic.ok: true`** with **`ignored_mismatch: true`** and adds a warning string (HTTP 200, `status: ready` unless another critical check fails).

### Verification

**PowerShell:**

```powershell
.\scripts\verify_production.ps1
```

**Bash:**

```bash
./scripts/verify_production.sh
```

Expected: env shows `SKIP=0` and `IGNORE=1`, `/health/live` and `/health/ready` succeed.

### Health Check Behavior

**With Skip (Old workaround):**

```json
{
  "status": "ready",
  "checks": {
    "alembic": {
      "ok": true,
      "detail": "skipped (THIRAMAI_SKIP_ALEMBIC_CHECK=1)"
    }
  }
}
```

**With Ignore Mismatch (Current):**

When DB revision matches expected:

```json
{
  "status": "ready",
  "checks": {
    "alembic": {
      "ok": true,
      "detail": "at expected head",
      "revision": "0078_add_ai_decisions_table",
      "expected": "0078_add_ai_decisions_table"
    }
  },
  "warnings": []
}
```

When DB and expected differ and ignore is on, see `checks.alembic.ignored_mismatch` and entries under `warnings`.

## Transition Checklist

- [x] Rebuild image with latest `api/routes/health.py`
- [x] Set `THIRAMAI_SKIP_ALEMBIC_CHECK=0`
- [x] Keep `THIRAMAI_HEALTH_IGNORE_ALEMBIC_MISMATCH=1`
- [ ] Apply env to the running container: `docker compose restart web` **does not** reload variables from `.env.production`. Use `docker compose ... up -d --force-recreate web`, or `./scripts/quick_restart.ps1` / `./scripts/quick_restart.sh`.
- [ ] Run `verify_production.ps1` (or `.sh`)
- [ ] Confirm `GET /health/ready` returns HTTP 200 and `status: ready`
