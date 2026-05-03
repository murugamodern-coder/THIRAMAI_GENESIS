# Runbook: Trading / execution halt

**Owner:** Trading & platform on-call  
**Last updated:** 2026-05-01  
**Last tested:** _Schedule per [README](./README.md)_  
**Default severity:** Critical (P0) when live capital is at risk; High (P1) for paper-only degradation

## Overview

Covers loss of reliable **trade execution**, **broker connectivity**, or **governance stop** conditions: elevated broker errors, automation continuing when unsafe, or alerts such as `TradingExecutionFastBurn`. The codebase exposes **paper trading** under Command Center routes; **live** execution depends on broker SDKs and environment (see `requirements-production.txt`).

THIRAMAI is not a broker — confirm regulatory and operational ownership for customer-facing outages.

## Symptoms

- [ ] Alert `TradingExecutionFastBurn` or `TradingExecutionSlowBurn` firing (`monitoring/prometheus/alert-rules.yml`).
- [ ] Grafana: `slo:trading:burn_rate:*` high; `thiramai_trade_broker_errors_total` rising vs `thiramai_trade_execution_latency_ms_count`.
- [ ] Users or monitors: orders not filling, repeated broker timeouts.
- [ ] `POST /governance/kill-switch` was enabled or risk limits tripped (`track_kill_switch` metrics).
- [ ] Global automation halt active (`global_halt: true` from autonomy safety).

## Impact assessment

**User impact:** Often **degraded** (failed orders) or **feature unavailable** (trading).  
**Business:** Revenue / reputation **High** if live trading; lower for paper-only labs.  
**Affected systems:** Broker adapters (`kiteconnect`, `fyers-apiv3`), `services/observability/business_metrics.py` counters, DB-backed execution logs, optional Redis for autonomy halt.

## Immediate actions (first 5 minutes)

1. Acknowledge alert; declare P0 if **live** money or open risk; else P1.
2. Open Grafana **Trading** + **SLO overview** dashboards (`thiramai-slo-overview`).
3. **Stop harmful automation** (requires authenticated operator with governance permissions):

   - **Global automation halt** (stops autonomous/action churn — see `api/routes/autonomy_safety.py`):
     - `POST /autonomy/safety/global-halt` with JSON body `{"enabled": true, "reason": "incident-YYYYMMDD-trading", "ttl_sec": 3600}` (adjust TTL).
   - **Per-user kill switch** (governance):  
     - `POST /governance/kill-switch` with `{"enabled": true, "reason": "..."}`.

   Use an authenticated session or API token as you do for other `/governance` calls.

4. Hit **`GET /health/system`** — if `503`, execution backlog / failure rate may already mark readiness as bad (`health.py` aggregates `_execution_runtime_metrics`).
5. **`GET /health/ready`** — inspect `checks.database_pool`, `checks.execution_runtime`, `checks.circuit_breakers`.

## Investigation steps

### Step 1 — Execution runtime snapshot

```bash
BASE="https://your-host.example.com"
curl -fsS "$BASE/health/system" | jq .
```

**Red flags:** high `failure_rate`, `stuck_running_count` above zero, or `ok: false`.

### Step 2 — Market / paper vs live

- Confirm **NSE equity session** (09:15–15:30 IST weekdays) if debugging “no fills” during the day.
- Paper path: authenticated **`GET /personal/os/paper-trading`** for Command Center paper state (router prefix `/personal/os`).

### Step 3 — Broker and credentials

- Check Zerodha / Fyers **status pages** and your token age (Kite access tokens expire daily unless refreshed).
- Application env: `KITE_*`, `FYERS_*` (see `.env.example`). For production secrets, see `docs/operations/secrets-management.md`.
- Logs: search for `401`, `403`, `token`, `rate limit`, broker exception types.

### Step 4 — Data plane

Follow **[Database pool exhaustion](./db-pool-exhaustion.md)** if pool saturated.  
Follow **[API availability](./api-availability.md)** if API 5xx dominate.

## Common root causes

| Cause | Indicators | Mitigation |
| ----- | ---------- | ---------- |
| Broker outage / brownout | Provider 5xx, timeouts, status page | Halt automation; communicate; no code fix |
| Expired / invalid API tokens | 401/403 from broker | Rotate credentials via your secret store; redeploy/restart if env-injected |
| DB pool or DB latency | `database_pool` unhealthy in `/health/ready` | Pool runbook + query tuning |
| Global halt / kill switch intentional | `global_halt` or governance flags | Confirm with risk owner before re-enabling |
| Bad deploy in trading stack | Correlate time with release | Roll back (see [TEMPLATE](./TEMPLATE.md#rollback)) |

## Resolution

1. Remove underlying cause (tokens, broker, DB, code).
2. **Clear halt flags** only after sign-off:
   - `POST /autonomy/safety/global-halt` with `"enabled": false` and reason.
   - `POST /governance/kill-switch` with `"enabled": false` when appropriate.
3. Validate with **small paper** or **minimal live** test per your policy; watch `thiramai_trade_*` metrics for ~15 minutes (longer than alert `for:` windows).
4. Confirm SLO burn returns to baseline.

## Communication

- Internal: use [TEMPLATE internal cadence](./TEMPLATE.md#communication).
- External: coordinate with compliance/support before promising resolution times on **investment** or **fund safety** topics.

## Escalation

- **Immediate:** if suspected **open-risk** or unreconciled positions with live broker — page trading lead + finance.
- **Broker-only outage:** executive + support comms may be required even when THIRAMAI code is healthy.

## Post-incident

- Postmortem within **24h** for P0 live-trading incidents; use `docs/incidents/TEMPLATE.md`.
- Reconcile broker statements vs internal logs if any orders succeeded during confusion window.

## Related

- [Autonomy safety API](../../api/routes/autonomy_safety.py)  
- [Governance kill switch](../../api/routes/governance.py)  
- [SLO management](../operations/slo-management.md)
