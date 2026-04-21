# Thiramai Incident Playbook

This playbook defines incident response standards for production reliability events, including SLO breaches and error budget exhaustion.

## 1. On-Call Rotation Guide

- **Primary on-call:** first responder for alerts and incident coordination.
- **Secondary on-call:** backup responder when primary is unavailable or overloaded.
- **Incident commander (IC):** assigned for P1/P2 incidents; drives timeline and communication.
- **Handover:** every shift must include open alerts, active mitigations, and unresolved risks.
- **Coverage expectation:** 24x7 coverage for P1/P2 alerts; business-hours coverage for P3/P4 unless escalated.

## 2. Severity Levels

- **P1 (Critical):** full or near-full outage, data loss risk, security impact, or severe customer impact.
- **P2 (High):** major degradation, SLO breach in progress, significant feature unavailability.
- **P3 (Medium):** partial impairment with workaround, localized customer impact, non-critical failures.
- **P4 (Low):** minor issue, cosmetic degradation, low operational risk.

## 3. Response Time SLAs

- **P1:** acknowledge within 5 minutes, mitigation started within 10 minutes, stakeholder update every 15 minutes.
- **P2:** acknowledge within 15 minutes, mitigation started within 30 minutes, update every 30 minutes.
- **P3:** acknowledge within 1 hour, mitigation started within 4 hours, update every business day.
- **P4:** acknowledge within 1 business day, scheduled fix in normal sprint cycle.

## 4. Alert Runbooks

### AvailabilitySLOBreach

**Trigger:** `rate(thiramai_requests_total{status=~"5.."}[5m]) > 0.005`

1. Confirm blast radius using `/health/live`, `/health/ready`, and Grafana availability panel.
2. Validate recent deploys, config changes, and dependency health (DB/Redis/AI providers).
3. Check app and reverse proxy logs for elevated 5xx classes and error signatures.
4. Roll back last risky deployment if regression is confirmed.
5. If unresolved within 15 minutes, escalate to platform lead and IC.

### LatencySLOBreach

**Trigger:** p95 latency > 500ms for 5 minutes

1. Validate saturation (CPU, memory, I/O, DB connection pool, Redis latency).
2. Identify slow endpoints from `thiramai_request_duration_seconds`.
3. Compare with deployment/change timeline and traffic spikes.
4. Apply mitigations: scale out workers, reduce expensive queries, enable safe degradation.
5. Escalate if p95 remains above threshold after 30 minutes.

### ErrorBudgetBurnHigh

**Trigger:** 1-hour 5xx burn above threshold

1. Calculate projected monthly burn from dashboard burn-rate panel.
2. Freeze non-essential production releases until burn stabilizes.
3. Prioritize remediation work over feature rollouts.
4. Launch focused reliability triage and assign owners.
5. Notify engineering leadership of budget risk status.

## 5. Escalation Paths

- **Step 1:** Primary on-call triages and acknowledges.
- **Step 2:** Secondary on-call joins if unresolved after SLA threshold.
- **Step 3:** Incident commander engages for P1/P2.
- **Step 4:** Escalate to platform lead / engineering manager for sustained impact.
- **Step 5:** Executive communication for major customer-facing incidents.

## 6. Communication Standards

- Open an incident channel immediately for P1/P2.
- Maintain a running timeline: detection, diagnosis, mitigations, decisions.
- Share status updates at severity-defined cadence.
- Publish customer-facing updates when applicable.

## 7. Post-Mortem Template

Use this template for all P1/P2 incidents and repeated P3 incidents.

```text
Incident Title:
Severity:
Start Time / End Time:
Duration:
Detected By:
Incident Commander:

Impact:
- Affected services/users
- Business/customer impact

Timeline:
- <timestamp> Detection
- <timestamp> Mitigation actions
- <timestamp> Recovery

Root Cause:
- Technical root cause
- Contributing factors

Resolution:
- What fixed the incident

Corrective Actions:
- [ ] Immediate fixes
- [ ] Preventive engineering actions
- [ ] Monitoring/alert improvements
- [ ] Documentation/runbook updates

SLO / Error Budget Impact:
- Which SLO was impacted
- Budget consumed

Owner:
Due Dates:
```
