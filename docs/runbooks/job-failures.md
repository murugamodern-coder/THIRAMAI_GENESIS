# Runbook: Background job failures

**Owner:** Platform on-call  
**Last updated:** 2026-05-01  
**Default severity:** Medium (P2)

## Overview

Scheduled workers (`workers/`, RQ, sovereign scheduler, alert scheduler) fail: stuck runs, rising failure rate in `/health/ready` → `execution_runtime`, or queue depth alerts.

## Reference metrics

- `GET /health/ready`: `checks.execution_runtime`, `checks.workers`
- `GET /health/system`: execution backlog and failure rate (24h window in `health.py`)
- Histogram: `thiramai_worker_job_duration_seconds`

## Symptoms

- [ ] `stuck_running_count` above zero, or `failure_rate` high enough to mark readiness not healthy.
- [ ] Redis heartbeat keys stale when `THIRAMAI_HEALTH_EXPECT_WORKERS` is set.

## Actions

1. Identify **which job family** from logs and metrics labels.
2. Check **Redis**, **DB**, and **broker** dependencies for that worker.
3. **Restart** worker deployment; drain queues if duplicate execution is risky.
4. If bug: disable job via feature flag or env (`THIRAMAI_INCIDENT_MODE` may reduce load — see `core/settings.py`).

## Related

- [Database pool exhaustion](./db-pool-exhaustion.md)  
- [Cache issues](./cache-issues.md)
