#!/bin/bash
set -euo pipefail

DATE=$(date +%Y-%m-%d)
mkdir -p audit_reports/$DATE

# Dependency audit
pip-audit -r requirements-base.txt \
  -f json > audit_reports/$DATE/pip_audit.json

# SBOM
bash scripts/generate_sbom.sh
cp sbom-base.json audit_reports/$DATE/

# Docker image scan
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy image thiramai-app:latest \
  --format json > audit_reports/$DATE/trivy.json

echo "Audit report generated: audit_reports/$DATE/"
