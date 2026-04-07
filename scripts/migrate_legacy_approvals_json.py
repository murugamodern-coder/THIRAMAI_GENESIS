"""
One-time migration: import rows from ``vault/pending_approvals.json`` into PostgreSQL ``approvals``.

Run: ``python scripts/migrate_legacy_approvals_json.py`` (requires DATABASE_URL).

Safe to re-run: skips rows whose UUID already exists in ``approvals``.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / "vault" / "pending_approvals.json"


def main() -> int:
    if not LEGACY.is_file():
        print(f"No legacy file at {LEGACY} — nothing to do.", file=sys.stderr)
        return 0

    from sqlalchemy.orm import Session

    from core.database import get_session_factory
    from core.db.models import Approval

    raw = json.loads(LEGACY.read_text(encoding="utf-8"))
    rows: list[dict] = raw if isinstance(raw, list) else raw.get("items") or raw.get("approvals") or []
    if not rows:
        print("Legacy JSON has no rows.", file=sys.stderr)
        return 0

    factory = get_session_factory()
    if factory is None:
        print("DATABASE_URL not set.", file=sys.stderr)
        return 1

    inserted = 0
    skipped = 0
    with factory() as session:
        assert isinstance(session, Session)
        for r in rows:
            rid = r.get("id") or r.get("approval_id")
            if not rid:
                skipped += 1
                continue
            try:
                key = uuid.UUID(str(rid).strip())
            except ValueError:
                skipped += 1
                continue
            if session.get(Approval, key):
                skipped += 1
                continue
            oid = int(r.get("organization_id") or r.get("org_id") or 0)
            if oid < 1:
                skipped += 1
                continue
            session.add(
                Approval(
                    id=key,
                    organization_id=oid,
                    action_type=str(r.get("action_type") or "legacy_import"),
                    risk_tier=str(r.get("risk_tier") or "high"),
                    status=str(r.get("status") or "pending"),
                    summary=str(r.get("summary") or "Legacy import"),
                    payload=dict(r.get("payload") or {}),
                    created_by=int(r["created_by"]) if r.get("created_by") is not None else None,
                )
            )
            inserted += 1
        session.commit()

    print(f"Migrated {inserted} rows; skipped {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
