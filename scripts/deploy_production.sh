#!/bin/bash
set -euo pipefail

TAG=${1:-latest}
echo "Deploying tag: $TAG"

if [ -f .current_deploy_tag ]; then
  cp .current_deploy_tag .previous_deploy_tag
fi

# Pull specific image tag
docker pull thiramai-app:$TAG

# Update compose to use specific tag
export DEPLOY_TAG=$TAG

# Run migrations
docker compose -f docker-compose.production.yml \
  --env-file .env.production \
  run --rm web alembic upgrade head

# Deploy with zero-downtime (rolling update)
docker compose -f docker-compose.production.yml \
  --env-file .env.production \
  up -d --no-deps web

# Health check
sleep 10
curl -f http://localhost:8000/health/ready || {
  echo "Health check failed! Rolling back to previous tag"
  bash scripts/rollback.sh
  exit 1
}

echo "Deploy successful: $TAG"
echo "$TAG" > .current_deploy_tag
