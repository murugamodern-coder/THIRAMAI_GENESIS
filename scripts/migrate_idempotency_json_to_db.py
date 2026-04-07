"""
One-time migration: import completed keys from ``vault/action_idempotency.json`` into ``idempotency_keys``.

Requires DATABASE_URL and applied DDL (``db/idempotency_and_jobs.sql``).

Usage::

    python scripts/migrate_idempotency_json_to_db.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT_FILE = ROOT / "vault" / "action_idempotency.json"


def main() -> int:
    if not VAULT_FILE.is_file():
        print("No vault/action_idempotency.json — nothing to migrate.", file=sys.stderr)
        return 0
    raw = json.loads(VAULT_FILE.read_text(encoding="utf-8"))
    keys = (raw or {}).get("keys") or {}
    if not keys:
        print("JSON has no keys — nothing to migrate.", file=sys.stderr)
        return 0
    if not (os.environ.get("DATABASE_URL") or "").strip():
        print("Set DATABASE_URL first.", file=sys.stderr)
        return 1
    from core.database import get_session_factory, reset_engine_cache
    from core.db.models import IdempotencyKey
    from sqlalchemy import select

    reset_engine_cache()
    factory = get_session_factory()
    if factory is None:
        print("Could not create engine from DATABASE_URL.", file=sys.stderr)
        return 1
    migrated = 0
    with factory() as session:
        with session.begin():
            for k, meta in keys.items():
                if not k:
                    continue
                exists = session.scalar(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == str(k)))
                if exists is not None:
                    continue
                rec = meta if isinstance(meta, dict) else {}
                completed_at = datetime.now(timezone.utc)
                ca = rec.get("completed_at_utc")
                if isinstance(ca, str):
                    try:
                        completed_at = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                row_meta = {"migrated_from_vault_json": True, **(rec.get("meta") or {})}
                action_type = str(rec.get("action_type") or "")
                session.add(
                    IdempotencyKey(
                        idempotency_key=str(k),
                        action_type=action_type,
                        meta=row_meta,
                        completed_at=completed_at,
                    )
                )
                migrated += 1
    print(f"Migrated {migrated} idempotency key rows (skipped existing).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
