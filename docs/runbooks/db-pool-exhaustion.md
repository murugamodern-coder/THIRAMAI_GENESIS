# Runbook: database connection pool exhaustion

## Symptoms

- Alerts: `DatabasePoolExhaustionWarning` or `DatabasePoolExhaustionCritical`.
- Grafana: `slo:db_pool:utilization` high; app logs may show pool timeout or queueing.
- Native metrics: `thiramai_db_pool_checked_out`,
  `thiramai_db_pool_configured`, `thiramai_db_pool_max_overflow_configured`,
  `thiramai_db_pool_timeouts_total` increasing.

## Immediate checks

1. Correlate with traffic spike or slow queries (DB query latency, `pg_stat_activity` if Postgres).
2. Look for **connection leaks** (sessions not closed, long-held connections in workers).
3. Verify replicas aren’t each opening excessive pools against a small DB `max_connections`.

## Mitigation

- **Short term:** scale app replicas only if DB can handle more total connections; otherwise reduce concurrency.
- **Tune (with validation):** `POOL_SIZE`, `MAX_OVERFLOW`, `POOL_TIMEOUT`, `POOL_RECYCLE` via
  `ThiramaiSettings` / env — see `core/settings.py` and `core/database.py`.
- **Fix root cause:** slow queries, missing indexes, N+1 patterns, stuck transactions.

## After resolution

- Confirm `thiramai_db_pool_timeouts_total` stops rising and utilization drops under warning threshold.
- Add a dashboard note or saved query for top wait events if this recurs.

## Related

- [Runbook template](./TEMPLATE.md) and [index](./README.md)
- [Database failover](./database-failover.md) if primary DB is unhealthy
