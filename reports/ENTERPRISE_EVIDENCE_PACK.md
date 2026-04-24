# THIRAMAI Evidence Pack

Generated (UTC): 2026-04-24T12:51:21.955841+00:00

## Chaos Validation
- Status: `pass`
- worker_resilience: exit_code=0
- autonomous_loop_safety: exit_code=0
- stress_concurrent_sells: exit_code=0

## Security Dependency Scan
- Status: `fail`
- Summary: Dependency vulnerabilities found or scan failed.

## AuthZ Coverage Audit
- Total routes scanned: `484`
- Likely unprotected route files: `0`

## Notes
- Static audits and local chaos checks are included.
- Live infrastructure chaos (DB/Redis/pod kill) should be run in staging/prod.
