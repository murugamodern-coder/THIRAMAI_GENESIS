# Thiramai Service Level Objectives (SLO)

This document defines measurable reliability objectives and error budgets for Thiramai production services.

## Service Level Objectives

### 1) API Availability SLO
- **Target:** 99.5% uptime per month
- **Error budget:** 0.5% (~3.6 hours/month downtime allowed)
- **SLI definition:** successful responses from `/health/live` over total probe attempts
- **Measurement source:** liveness probe success rate and request-level error ratio

### 2) API Latency SLO
- **Target:** 95% of API requests complete in under 500ms (p95 < 500ms)
- **SLI definition:** `thiramai_request_duration_seconds` histogram quantile at 0.95
- **Measurement source:** API response-time metrics derived from access/request telemetry

### 3) Dashboard Load SLO
- **Target:** 95% of dashboard loads complete in under 3 seconds
- **SLI definition:** frontend page load duration for Command Center dashboard route
- **Measurement source:** frontend performance metrics (browser instrumentation/RUM)

### 4) Worker Job SLO
- **Target:** 99% of background jobs complete within 5 minutes
- **SLI definition:** `thiramai_worker_job_duration_seconds` under 300 seconds for 99% of jobs
- **Measurement source:** job queue processing duration metrics

## Error Budget Policy

- **Budget period:** calendar month
- **Availability budget:** 0.5% of monthly time
- **Burn-rate guidance:**
  - Warn when short-window error rate indicates rapid burn
  - Escalate immediately on sustained breach conditions
- **Operational response:** during high burn, pause non-critical releases and prioritize reliability fixes

## Review Cadence

- Review SLO attainment weekly during operations review.
- Perform monthly budget reset and trend analysis.
- Trigger post-incident action items when SLOs are breached.
