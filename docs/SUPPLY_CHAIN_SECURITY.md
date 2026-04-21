# Supply Chain Security

## Dependency Strategy

- All production deps pinned to exact versions
- SBOM generated at every build
- Weekly automated pip-audit in CI

## How to update a dependency

1. Update version in requirements-base.txt
2. Run scripts/audit_deps.sh
3. Run full test suite
4. Update SBOM

## Vulnerability response SLA

- Critical: fix within 24 hours
- High: fix within 7 days
- Medium: fix within 30 days
