# Runbook: Security breach / suspected compromise

**Owner:** Security lead + platform on-call  
**Last updated:** 2026-05-01  
**Default severity:** Critical (P0)

## Overview

Indicators of **unauthorized access**, **credential leak**, **data exfiltration**, or **malicious activity** in THIRAMAI infrastructure or dependencies.

## Symptoms

- [ ] Unexpected admin actions, new API keys, unknown logins, mass downloads.
- [ ] IDS or EDR alerts; cloud “impossible travel”; spike in failed auth then success from odd IPs.
- [ ] Customer report of account takeover.

## Immediate actions (first hour)

1. **Do not** delete evidence. Snapshot logs, WAF request IDs, cloud audit trails.
2. Page **security** and **legal** per your org chart.
3. **Rotate** suspected credentials (broker, DB, cloud IAM, signing keys) via your secret manager — see `docs/operations/secrets-management.md`.
4. Consider **blocking** attacker IPs or sessions at the edge; **disable** compromised accounts after a quick inventory.
5. If ransomware or large-scale leak is suspected: **isolate** backups from production networks.

## Investigation

- Review audit logging and admin actions (see `api/routes/audit.py` and org policies).
- Correlate JWT or session issuance with authentication routes.
- Inspect Postgres and Redis for unusual data or keys.

Do **not** document exploit details in public tickets until security clears it.

## Escalation

Involve **security** and **legal**; notify customers or regulators only per your breach playbook.

## Post-incident

- Forced credential rotation, hardening tasks, and IR report.
- Update `docs/INCIDENT_PLAYBOOK.md` if gaps were found.

## Related

- [Data loss](./data-loss.md) if integrity or availability of data is in question
