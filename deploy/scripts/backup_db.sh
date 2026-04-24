#!/bin/sh
set -eu

TS="$(date +%Y%m%d_%H%M%S)"
OUT="/backups/thiramai_${TS}.sql.gz"

pg_dump -h db -U "${POSTGRES_USER:-thiramai}" "${POSTGRES_DB:-thiramai}" | gzip > "${OUT}"

# Keep last 14 backups.
ls -1t /backups/thiramai_*.sql.gz 2>/dev/null | awk 'NR>14' | xargs -r rm -f
