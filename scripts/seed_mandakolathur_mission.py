#!/usr/bin/env python3
"""Upsert a sample Mission Hub row: Mandakolathur Land Register (progress %)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from services.life_os_service import upsert_personal_mission

EMAIL = (os.getenv("THIRAMAI_PLANNER_USER_EMAIL") or "admin@thiramai.local").strip().lower()
TITLE = "Mandakolathur Land Register"
PROGRESS = int((os.getenv("THIRAMAI_SEED_MISSION_PROGRESS") or "35").strip() or "35")


def main() -> int:
    from sqlalchemy import select
    from core.database import get_session_factory
    from core.db.models import User

    factory = get_session_factory()
    if factory is None:
        print("DATABASE_URL missing", file=sys.stderr)
        return 1
    with factory() as session:
        u = session.execute(select(User).where(User.email == EMAIL)).scalar_one_or_none()
        if u is None:
            print("No user", EMAIL, file=sys.stderr)
            return 1
        uid = int(u.id)
    ok, msg, mid, _ = upsert_personal_mission(
        user_id=uid,
        mission_id=None,
        title=TITLE,
        description="Land registration workflow — use planner checklist + vault for deeds.",
        status="open",
        progress_percent=PROGRESS,
    )
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print("OK mission_id", mid, TITLE, PROGRESS, "%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
