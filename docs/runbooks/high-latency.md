# Runbook: High latency

**Owner:** Platform on-call  
**Last updated:** 2026-05-01  
**Default severity:** High (P1) when SLO breached

## Overview

End-user latency degrades: `APILatencyWarning` / `APILatencyCritical` or Grafana shows `slo:api_latency:p95:5m` above targets (`monitoring/prometheus/alert-rules.yml`).

## Symptoms

- [ ] p95 above **750 ms** (warning) or **1 s** (critical) sustained.
- [ ] Command Center or API “spinning”; TTFB high at edge.

## Immediate actions

1. Open **SLO overview** + **Overview** Grafana dashboards.
2. Slice `thiramai_request_duration_seconds_bucket` by **endpoint** label if cardinality allows.
3. Check **database** slow queries and **pool** (`/health/ready` → `database_pool`).
4. Check **dependency** timeouts (LLM, Redis, external HTTP).

## Common causes

- Missing index or N+1 queries.
- Pool wait time high — [db-pool-exhaustion](./db-pool-exhaustion.md).
- Cold start / CPU saturation — see **memory-leak** for growth; check `thiramai_cpu_usage_pct`.
- Region misrouting or TLS offload issues.

## Resolution

Optimize hot path, scale out, or shed load (rate limits, disable heavy features via flags such as `THIRAMAI_INCIDENT_MODE` / env documented in `core/settings.py`).

## Related

- [API availability](./api-availability.md)  
- [Cache issues](./cache-issues.md) if Redis slow
