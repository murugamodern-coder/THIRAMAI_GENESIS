# Runbook: [Incident Type]

**Owner:** [Team or role — e.g. Platform on-call]  
**Last updated:** YYYY-MM-DD  
**Last tested:** YYYY-MM-DD (see [Runbook index README](./README.md))  
**Default severity:** [Critical | High | Medium]

## Overview

One short paragraph: what this incident class is, typical blast radius, and which users or systems feel it first.

## Symptoms

Observable indicators. Check all that apply during triage:

- [ ] Symptom 1 (metric, log line, or user report)
- [ ] Symptom 2
- [ ] Related alerts: `AlertNameA`, `AlertNameB` (from Prometheus / Alertmanager)
- [ ] User-visible impact: [None | Degraded | Outage | Data risk]

## Impact assessment

**User impact**

- [ ] Full product unavailable
- [ ] Degraded performance or partial features
- [ ] Single tenant / region
- [ ] Internal-only (no customer impact yet)

**Business impact (qualitative)**

| Area        | Level (High / Medium / Low / None) |
| ----------- | ----------------------------------- |
| Revenue     |                                     |
| Reputation  |                                     |
| Compliance  |                                     |

**Affected systems**

- [ ] API / app tier
- [ ] Database
- [ ] Cache / queue
- [ ] Workers / schedulers
- [ ] Broker / external API
- [ ] Other: [name]

## Immediate actions (first 5 minutes)

1. Acknowledge the alert in PagerDuty or your on-call tool.
2. Open or reuse an incident Slack channel (e.g. `#incident-YYYYMMDD-short-name`).
3. Assign **incident commander** and note **severity** (P0–P3) using [Escalation](#escalation) below.
4. Open Grafana: [SLO overview](https://grafana.example.com/d/thiramai-slo-overview) (replace host) and the dashboard linked in this runbook’s “Related” section.
5. Record **start time** (timezone: IST or UTC — be explicit).

## Investigation steps

### Step 1 — Quick health

Replace `BASE` with your public or internal base URL (e.g. `https://app.example.com`).

```bash
curl -fsS "$BASE/health/live"
curl -fsS "$BASE/health/ready" | head -c 4000
```

**Expected:** `/health/live` returns 200. `/health/ready` returns 200 with `status":"ready"` when dependencies are healthy.

**If `ready` is 503:** parse JSON `checks` for `database`, `redis`, `database_pool`, `workers`, `execution_runtime`.

### Step 2 — Narrow the blast radius

- Confirm whether the issue is global, single region, or single deployment revision.
- Correlate with deploys, config changes, traffic spikes, or provider incidents.

### Step 3 — Deep dive (customize per runbook)

Add service-specific commands (SQL, redis-cli, kubectl, provider consoles). Prefer linking to sibling runbooks instead of duplicating long procedures.

**Expected vs red flags:** document what “good” looks like and what should trigger escalation.

## Common root causes

### Cause A — [Title]

**Probability:** High | Medium | Low  

**Indicators:** metrics, logs, dashboard panels.

**Mitigation (stop the bleeding):** short steps, ideally reversible.

**Permanent fix:** ticket or design note; link to code or infra change.

### Cause B — [Title]

(Same structure.)

## Resolution

### If root cause is [A]

1. Apply mitigation (with change record).
2. Verify SLOs / health endpoints recover.
3. Watch error rate and latency for two probe intervals longer your alert `for:` duration.

### If root cause is [B]

(Alternative path.)

## Rollback

If a recent release is suspected:

1. Identify running revision (image tag, git SHA, or platform equivalent).
2. Roll back using your standard path (e.g. `kubectl rollout undo deployment/thiramai-app`, or platform “rollback release”).
3. Re-run `/health/live` and `/health/ready`.
4. Confirm metrics return to baseline.

## Communication

### Internal status updates

Post to the incident channel using this shape (adjust frequency by severity):

**P0:** at least every 15 minutes until mitigated.  
**P1:** at least every 30 minutes.  
**P2/P3:** at least hourly or on material change.

Example line:

`[14:32 IST] INVESTIGATING | Impact: API 5xx elevated EU | Suspected: DB pool | Actions: scaling + pool check | Next: 14:47`

### External / customer comms

Use your status page and support templates. For a significant customer-visible outage, notify support leadership before mass email.

**Status page:** `https://status.example.com` (replace).  
Do **not** put secrets, internal hostnames, or credentials in customer text.

## Escalation

**Escalate when:**

- Mitigation is unclear after the timebox in this runbook (or **30 minutes** if unspecified).
- Impact spreads to multiple systems or regions.
- Data loss, suspected breach, or compliance trigger applies.
- On-call needs a decision that only a lead/manager can make.

**Suggested path (customize to your org):**

| Level | Role |
| ----- | ---- |
| L1 | Primary on-call engineer |
| L2 | Team lead / senior on-call |
| L3 | Engineering manager |
| L4 | Director / CTO |
| L5 | Exec (major outage, legal, or media) |

**Contact:** keep phone trees and Slack user groups in a **private** ops doc, not in this repository.

## Post-incident

- Confirm recovery: health checks green, SLO burn stable, no new related alerts.
- Capture timeline, root cause, and customer impact.
- File postmortem within 48 hours for P0/P1 using `docs/incidents/TEMPLATE.md`.
- Update this runbook if steps were wrong or incomplete.
- Schedule the next [runbook test](../README.md#testing-schedule).

## Testing this runbook

- **Frequency:** Quarterly minimum for P0/P1; monthly for trading or payment-adjacent flows.
- **Method:** in **staging**, inject or simulate failure (feature flag, chaos test, or scaled load); execute checklist with a second engineer shadowing.
- **Record:** date, participants, gaps, follow-up issues.

## Related documentation

- Monitoring: `monitoring/grafana/dashboards/`, `monitoring/prometheus/alert-rules.yml`
- Alerts index: [Runbooks README](./README.md)
- Code / architecture: [links]

## Revision history

| Date | Author | Changes |
| ---- | ------ | ------- |
| YYYY-MM-DD | [Name] | Initial version |
