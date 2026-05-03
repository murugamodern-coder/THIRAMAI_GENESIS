# Incident runbooks

Operational response guides for THIRAMAI Genesis production. All runbooks follow the same skeleton: see **[TEMPLATE.md](./TEMPLATE.md)** (symptoms, impact, first 5 minutes, investigation, escalation, communication, testing).

Alert names reference `monitoring/prometheus/alert-rules.yml` where applicable.

## Critical (P0) — page immediately

| Runbook | When to use |
| ------- | ----------- |
| [Trading / execution halt](./trading-halt.md) | Broker errors, execution SLO burn, unsafe automation |
| [Database failover](./database-failover.md) | Primary DB unavailable; need promotion or URL change |
| [Complete service outage](./complete-outage.md) | Users cannot reach app at all |
| [Security breach](./security-breach.md) | Suspected compromise or credential abuse |
| [Data loss](./data-loss.md) | Corruption, bad migration, restore needed |

## High priority (P1) — page on-call (business hours or 24/7 per roster)

| Runbook | When to use |
| ------- | ----------- |
| [API availability](./api-availability.md) | Error budget burn, sustained 5xx |
| [Database pool exhaustion](./db-pool-exhaustion.md) | Pool at capacity; readiness degraded |
| [High latency](./high-latency.md) | `APILatency*` alerts, bad p95/p99 |
| [PolicyEngine / DecisionBrainV2](./policy-engine-failure.md) | PolicyEngine failures, legacy fallback, strict-mode 503 on `/chat/decision` |

## Medium priority (P2/P3) — Slack / ticket first

| Runbook | When to use |
| ------- | ----------- |
| [Memory leak](./memory-leak.md) | RSS growth, OOM risk |
| [Certificate expiry](./certificate-expiry.md) | TLS renewal |
| [Disk space](./disk-space.md) | Volume almost full |
| [Background jobs](./job-failures.md) | Workers, execution_runtime unhealthy |
| [Rate limits](./rate-limits.md) | 429 storms, dependency throttles |
| [Cache / Redis](./cache-issues.md) | Redis ping fails, halt flags broken |

## Runbook standards

Every runbook should cover:

1. Symptoms and **linked alerts**  
2. Impact assessment  
3. **First 5 minutes**  
4. Investigation with **copy-paste commands** (placeholders allowed)  
5. Common causes + mitigations  
6. Resolution / rollback pointers  
7. Communication + **escalation** (see TEMPLATE)  
8. Post-incident / testing notes  

## Testing schedule

Run drills in **staging** or a sandbox project. Record outcomes in your ticketing system.

| Runbook | Suggested frequency | Last tested | Next test |
| ------- | ------------------- | ----------- | --------- |
| Trading halt | Monthly | _YYYY-MM-DD_ | _YYYY-MM-DD_ |
| Database failover | Quarterly | _YYYY-MM-DD_ | _YYYY-MM-DD_ |
| Complete outage | Quarterly | _YYYY-MM-DD_ | _YYYY-MM-DD_ |
| Security breach | Semi-annual table-top | _YYYY-MM-DD_ | _YYYY-MM-DD_ |
| API availability | Quarterly | _YYYY-MM-DD_ | _YYYY-MM-DD_ |

Update the **Last tested** column after each drill.

**Automation:** `python scripts/test_runbook.py --all-synthetics` runs **read-only** HTTP checks against a base URL (default `http://127.0.0.1:8000`). See script help.

## Ownership (customize)

| Area | Owns |
| ---- | ---- |
| Trading & risk | Trading halt, rate limits (broker) |
| Platform | Outage, latency, pool, cache, jobs, memory, disk |
| Infrastructure | DB failover, certificates |
| Security | Breach, IR coordination |

## New runbooks

1. Copy `TEMPLATE.md`.  
2. Wire alerts and dashboards.  
3. Peer review with on-call lead.  
4. Add a row to this README and schedule a first drill.

## Incident log

Postmortems: use **`docs/incidents/TEMPLATE.md`** and store under `docs/incidents/` with dated filenames.
