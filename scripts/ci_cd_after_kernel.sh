#!/usr/bin/env bash
# Local CD hook after kernel sandbox approval (THIRAMAI_CI_CD_MODE=local_script).
#
# Environment:
#   THIRAMAI_KERNEL_PAYLOAD_JSON — JSON from services/ci_cd_trigger.py (patch path, pytest code).
#   THIRAMAI_DEPLOY_COMPOSE_FILE — optional, default docker-compose.production.yml
#   THIRAMAI_DEPLOY_ENV_FILE     — optional, default .env.production
#   THIRAMAI_KERNEL_APPLY_PATCH  — set to 1 to ``git apply`` var/sandbox_patches/candidate.patch before compose (dangerous on dirty trees)
#
# Customize this script on the VPS (git pull, compose build, push to registry, etc.).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

COMPOSE="${THIRAMAI_DEPLOY_COMPOSE_FILE:-docker-compose.production.yml}"
ENVF="${THIRAMAI_DEPLOY_ENV_FILE:-.env.production}"

echo "[ci_cd_after_kernel] payload (truncated): ${THIRAMAI_KERNEL_PAYLOAD_JSON:0:200}..."

PATCH_FILE="${ROOT}/var/sandbox_patches/candidate.patch"
if [[ "${THIRAMAI_KERNEL_APPLY_PATCH:-}" == "1" && -f "$PATCH_FILE" ]]; then
  echo "[ci_cd_after_kernel] applying sandbox patch (THIRAMAI_KERNEL_APPLY_PATCH=1)..."
  if git apply --check "$PATCH_FILE" 2>/dev/null; then
    git apply "$PATCH_FILE"
  else
    echo "[ci_cd_after_kernel] warn: git apply --check failed; skipping apply."
  fi
fi

if [[ -f "$ENVF" && -f "$COMPOSE" ]]; then
  docker compose -f "$COMPOSE" --env-file "$ENVF" up -d --build
  echo "[ci_cd_after_kernel] docker compose up completed."
else
  echo "[ci_cd_after_kernel] skip compose: missing $ENVF or $COMPOSE (set paths or commit patch manually)."
fi
