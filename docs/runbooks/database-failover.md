# Runbook: Database failover

**Owner:** Infrastructure / DBA + platform on-call  
**Last updated:** 2026-05-01  
**Last tested:** _Schedule per [README](./README.md)_  
**Default severity:** Critical (P0)

## Overview

Primary **PostgreSQL** (or your configured engine) is unavailable or read-only when writes are required. THIRAMAI uses SQLAlchemy (`core/database.py`) with pool settings from `ThiramaiSettings`. There is **no automatic failover** in-application; failover is an **infrastructure** procedure (RDS, Cloud SQL, Patroni, etc.).

## Symptoms

- [ ] `/health/ready` **503** with `checks.database.ok: false` or connection errors in `detail`.
- [ ] Logs: `connection refused`, `timeout`, `too many connections`, authentication failures.
- [ ] All write paths fail; possibly `/health/live` still 200 (process up, DB down).
- [ ] Grafana: DB-related panels empty; `thiramai_db_pool_*` stale or zero if scrapes fail.

## Impact assessment

**User impact:** Usually **full outage** for authenticated product paths.  
**Business / compliance:** **High**; data durability depends on your storage layer.

## Immediate actions (first 5 minutes)

1. P0 incident; page infra + app on-call.
2. Confirm blast radius (single AZ vs global).
3. `curl -fsS "$BASE/health/ready"` and capture full JSON (redact secrets).
4. If **pool exhaustion** but DB alive, see **[db-pool-exhaustion](./db-pool-exhaustion.md)** first.

## Investigation

```bash
# From an app jump box or VPN — use your real host/user/db
psql "$DATABASE_URL" -c "select 1"
psql "$DATABASE_URL" -c "select pg_is_in_recovery();"
```

**Expected:** `1` and `f` on primary (writable).

**On managed cloud:** use provider console for instance status, **replica lag**, **failover** button, **multi-AZ** state.

## Failover (generic checklist)

Procedures differ by provider. Adapt the following.

1. **Assess replica lag** — promote only if lag is within RPO policy (often &lt; 60s).
2. **Stop writers** — scale app to 0 or enable maintenance page if split-brain risk.
3. **Promote replica** (e.g. AWS RDS `promote-read-replica`, GCP **promote** Cloud SQL replica, Patroni `switchover`).
4. **Update `DATABASE_URL`** (secret manager + reload / redeploy). App reads URL via settings / secrets (see `core/secrets_manager.py`, `get_database_url`).
5. **Rollback DNS** or **connection policy** if you use proxy (PgBouncer, RDS Proxy).
6. **Restart** app workers so pools reconnect cleanly (`kubectl rollout restart …` or equivalent).
7. **Verify** `/health/ready` = 200 and run a smoke write (e.g. login or trivial update in staging first).

## After old primary returns

- Rebuild it as a **replica** of the new primary; verify replication before cutting traffic back.
- Document RPO/RTO achieved.

## Related

- [Database pool exhaustion](./db-pool-exhaustion.md)  
- [Complete service outage](./complete-outage.md)

## Communication & escalation

Use [TEMPLATE](./TEMPLATE.md#escalation). Involve **legal/compliance** if customer data availability or loss is unclear.
