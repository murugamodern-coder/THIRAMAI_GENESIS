#!/bin/bash
set -euo pipefail

PREVIOUS_TAG=$(cat .previous_deploy_tag 2>/dev/null || echo "")
if [ -z "$PREVIOUS_TAG" ]; then
  echo "No previous tag found! Cannot rollback."
  exit 1
fi

echo "Rolling back to: $PREVIOUS_TAG"
export DEPLOY_TAG="$PREVIOUS_TAG"
docker pull thiramai-app:$PREVIOUS_TAG
docker compose -f docker-compose.production.yml \
  --env-file .env.production \
  up -d --no-deps web

echo "$PREVIOUS_TAG" > .current_deploy_tag
echo "Rollback complete: $PREVIOUS_TAG"
