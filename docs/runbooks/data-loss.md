# Runbook: Data loss or corruption

**Owner:** Infrastructure + app on-call + DBA  
**Last updated:** 2026-05-01  
**Default severity:** Critical (P0)

## Overview

Suspected **wrong deletes**, **failed migration**, **replication split-brain**, or **restore** need after bad deploy. THIRAMAI relies on Postgres for most tenant state; some features use SQLite or files under `vault/` — know which subsystems you run.

## Symptoms

- [ ] Customers report missing records; audits show unexpected `DELETE` or `UPDATE` scope.
- [ ] Migration partially applied (`/health/ready` Alembic check fails).
- [ ] Backup job failures correlated with incident window.

## Immediate actions

1. **Stop destructive jobs** (migrations, pruning workers) until scope is known.
2. Take a **fresh backup** or storage snapshot **before** further writes if disk allows.
3. Page **DBA + security** if tampering suspected ([security-breach](./security-breach.md)).
4. Read-only mode: route traffic to maintenance or scale writers to zero if you must halt corruption.

## Investigation

- Identify **time window** and **tables** affected (`pg_stat_activity`, application logs, audit trail).
- Confirm whether loss is **logical** (bug) vs **physical** (disk).
- For Alembic: compare `alembic_version` to `EXPECTED_ALEMBIC_REVISION` (`core/migration_head.py`).

## Resolution paths

| Scenario | Action |
| -------- | ------ |
| Bad application write | Fix forward + selective restore from backup or PITR |
| Bad migration | Restore DB to pre-migration snapshot + fix migration in lower env |
| Operator error | Restore object or table from backup; document in postmortem |

## Post-incident

- Customer communication if PII or financial records touched.
- Ticket for **backup restore drill** and **migration test** improvements.

## Related

- [Database failover](./database-failover.md)  
- [Security breach](./security-breach.md)
