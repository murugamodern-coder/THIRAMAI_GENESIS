#!/bin/bash
set -euo pipefail
echo "Running pre-deploy checks..."

# 1. Static asset integrity
bash scripts/verify_static.sh

# 2. Requirements are pinned
python3 scripts/gate_pip_audit_high_critical.py \
  requirements-base.txt \
  requirements-production.txt

# 3. Alembic migrations are consistent
docker compose -f docker-compose.production.yml \
  --env-file .env.production \
  run --rm web alembic check

# 4. Health endpoint responds
curl -f http://localhost:8000/health/live

echo "All pre-deploy checks passed!"
