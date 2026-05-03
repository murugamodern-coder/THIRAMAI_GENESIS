# Runbook: Certificate expiry

**Owner:** Infrastructure on-call  
**Last updated:** 2026-05-01  
**Default severity:** Medium (P2) until within renewal window — elevate to P1 close to expiry

## Overview

Public TLS certificates for `*.thiramai…` or load balancers approach **Not After** date; browsers show warnings or API clients fail validation.

## Symptoms

- [ ] Monitoring alert on **days to expiry** (configure in your cert monitor or cloud ACM).
- [ ] `curl: SSL certificate problem: certificate has expired`.

## Actions

1. Confirm **which** hostnames use which cert (LB, CDN, k8s ingress).
2. **Renew** via ACME / provider console; deploy new chain.
3. Validate with `openssl s_client -connect host:443 -servername host` and external SSLLabs-style check.
4. Update **inventory** of auto-renew jobs.

## Related

- [Complete outage](./complete-outage.md) if all users hit bad cert
