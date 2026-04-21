#!/usr/bin/env bash
# Prune old files under BACKUP_ROOT (cron-safe). Does not touch application code.
#
# Crontab example (weekly Sunday 03:30):
#   30 3 * * 0 BACKUP_ROOT=/var/backups/thiramai RETENTION_DAYS=14 /opt/thiramai/deploy/scripts/backup-cleanup.sh >>/var/log/thiramai-backup-cleanup.log 2>&1

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/thiramai}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

if [[ ! -d "$BACKUP_ROOT" ]]; then
  echo "$(date -Is) backup-cleanup: BACKUP_ROOT does not exist ($BACKUP_ROOT), nothing to do."
  exit 0
fi

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || [[ "$RETENTION_DAYS" -lt 1 ]]; then
  echo "$(date -Is) backup-cleanup: invalid RETENTION_DAYS=$RETENTION_DAYS" >&2
  exit 1
fi

echo "$(date -Is) backup-cleanup: pruning files older than ${RETENTION_DAYS} days under $BACKUP_ROOT"

find "$BACKUP_ROOT" -type f -mtime "+${RETENTION_DAYS}" -print -delete || true

# Remove empty directories bottom-up (ignore errors)
find "$BACKUP_ROOT" -mindepth 1 -type d -empty -delete 2>/dev/null || true

echo "$(date -Is) backup-cleanup: done."
