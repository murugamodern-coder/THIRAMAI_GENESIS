#!/usr/bin/env bash
# Production release helper: gates + git tag push (Compose/Kubernetes agnostic).
# Usage: bash scripts/deploy_production.sh
# On Windows: Git Bash or WSL.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "================================"
echo "THIRAMAI — production tag helper"
echo "================================"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" && "$BRANCH" != "master" ]]; then
  echo "Not on main/master (current: $BRANCH). Continue? [y/N]"
  read -r ans
  [[ "${ans:-}" == "y" || "${ans:-}" == "Y" ]] || exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree not clean:"
  git status --short
  exit 1
fi

echo "Running pytest (quiet)..."
python -m pytest tests/ -q

echo "Coverage gate (if script present)..."
if [[ -f scripts/check_critical_coverage.py ]]; then
  python scripts/check_critical_coverage.py || {
    echo "Critical coverage check failed."
    exit 1
  }
fi

read -r -p "Version label for tag (e.g. 1.2.3): " VERSION
[[ -n "${VERSION:-}" ]] || { echo "Version required."; exit 1; }

TAG="v${VERSION}-production"
read -r -p "Create and push tag $TAG ? [y/N]: " CONFIRM
[[ "${CONFIRM:-}" == "y" || "${CONFIRM:-}" == "Y" ]] || { echo "Cancelled."; exit 0; }

git tag -a "$TAG" -m "Production release $VERSION"
git push origin "$TAG"

echo ""
echo "Tag pushed: $TAG"
echo "Next: run your CI/CD or on-host compose deploy; then:"
echo "  python scripts/verify_deployment.py --url https://YOUR_HOST"
