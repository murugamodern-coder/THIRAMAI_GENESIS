# SLO management

Formal objectives and error-budget policies for production. Machine-readable
definitions live in `monitoring/slos/slo-definitions.yml`; Prometheus recording
rules in `monitoring/prometheus/recording-rules.yml` and alerts in
`monitoring/prometheus/alert-rules.yml`.

## Service level objectives

### API availability

- **Objective:** 99.9% of HTTP requests return a non-5xx status over a 30-day window.
- **Error budget:** about 43.2 minutes of “bad” availability per month at steady traffic.
- **Measurement:** `thiramai_requests_total` — success excludes `status=~"5.."`.
- **Burn-rate alerts:** fast (5m + 1h windows at 14.4×) and slow (6h at 6×); see alert rules.

### API latency

- **Objective:** p95 latency under 500 ms.
- **Measurement:** `histogram_quantile(0.95, sum by (le) (rate(thiramai_request_duration_seconds_bucket[5m])))`.
- **Alerts:** warning above 750 ms sustained; critical above 1 s sustained.

### Trading execution (proxy SLI)

- **Objective:** 99.5% successful execution attempts vs broker errors (30-day mental model).
- **Measurement:** `thiramai_trade_execution_latency_ms_count` minus
  `thiramai_trade_broker_errors_total`, normalized when there is traffic. Prefer a
  dedicated `thiramai_trade_execution_total{result=...}` counter when the execution
  path is refactored.

### Decision engine latency

- **Objective:** p99 under 200 ms on `thiramai_decision_latency_seconds`.
- **Alert:** warning when p99 above 500 ms for 10 minutes.

### Database connection pool

- **Objective:** utilization (checked out ÷ configured + max overflow) stays under 95%.
- **Metrics:** `thiramai_db_pool_checked_out`, `thiramai_db_pool_configured`,
  `thiramai_db_pool_max_overflow_configured`.

## Error budget policy

- **Budget remaining above 50%:** normal releases and experiments.
- **Between 25% and 50%:** tighten change control; watch burn rate and latency SLOs.
- **Below 25%:** feature freeze on risky work; reliability and RCA before broad rollout.
- **0% or less (exhausted or negative in Grafana):** emergency posture — stabilize,
  stop unrelated changes, executive comms as per your incident process.

## Alerting philosophy

Alerts are tied to **burn rate** (availability / trading) or **direct SLI breach**
(latency / pool). Critical routes page (PagerDuty) and mirror to Slack; warnings
go to Slack only. Alertmanager config: `monitoring/alertmanager/alertmanager.yml`
(expand env for webhooks / routing keys).

## Dashboards

- **SLO overview (recording rules):** import `monitoring/grafana/dashboards/slo-overview.json`
  (uid `thiramai-slo-overview`). Set the Prometheus datasource UID to match your stack
  (`PROMETHEUS_DS_UID` placeholder).
- **Legacy detail board:** `monitoring/grafana/slo_dashboard.json` (uid `thiramai-slo`).

Production URL examples (replace host with yours), e.g.
`https://grafana.example.com/d/thiramai-slo-overview`.

## Runbooks

When an alert fires, open the **runbook** in the annotation (under `docs/runbooks/`)
and record actions in the incident channel.

## Monthly SLO review

On the first working Monday of each month:

1. Compare 30-day SLIs to objectives (Grafana + Prometheus).
2. Review error budget consumption and any burn-rate pages.
3. Update `monitoring/slos/slo-definitions.yml` if product expectations changed.
4. File engineering backlog items for repeated near-misses.
