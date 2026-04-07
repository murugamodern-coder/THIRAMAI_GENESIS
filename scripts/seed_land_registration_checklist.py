#!/usr/bin/env python3
"""
Merge land-registration checklist items into today's ``daily_plans`` row for a user.

Creates four sub-tasks (if missing by title):
  - Balance amount check
  - 3-option registration choice
  - Lawyer document import
  - Mediator call

Optional: prepends a short Markdown section to ``plan_text`` when it does not mention land registration.

Environment:
  THIRAMAI_PLANNER_USER_EMAIL — default ``admin@thiramai.local``
  THIRAMAI_PLANNER_FOR_DATE — optional ``YYYY-MM-DD`` (default: today UTC)

Usage:
  python scripts/seed_land_registration_checklist.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv(dotenv_path=ROOT / ".env", override=True)

from core.database import get_session_factory
from core.db.models import DailyPlan, User
from services.executive_os_service import _normalize_checklist, upsert_daily_plan

LAND_MARK = "land registration"
MD_HEADER = """## Land registration — focus
Parent goal: complete registration workflow. Use the **checklist** below for sub-tasks and reminders.

"""

DEFAULT_ITEMS: list[dict[str, str | bool | None]] = [
    {"title": "Balance amount check", "done": False, "remind_at": None},
    {"title": "3-option registration choice", "done": False, "remind_at": None},
    {"title": "Lawyer document import", "done": False, "remind_at": None},
    {"title": "Mediator call", "done": False, "remind_at": None},
]


def _parse_date(s: str | None) -> date:
    if not (s or "").strip():
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return datetime.now(timezone.utc).date()


def main() -> int:
    factory = get_session_factory()
    if factory is None:
        print("ERROR: DATABASE_URL not set.", file=sys.stderr)
        return 1

    email = (os.getenv("THIRAMAI_PLANNER_USER_EMAIL") or "admin@thiramai.local").strip().lower()
    for_d = _parse_date(os.getenv("THIRAMAI_PLANNER_FOR_DATE"))

    with factory() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            print(f"ERROR: no user with email {email}", file=sys.stderr)
            return 1
        uid = int(user.id)

        row = session.execute(
            select(DailyPlan).where(DailyPlan.user_id == uid, DailyPlan.for_date == for_d).limit(1)
        ).scalar_one_or_none()

        existing_titles: set[str] = set()
        existing_items: list[dict] = []
        plan_text = ""
        status = "draft"
        if row is not None:
            plan_text = row.plan_text or ""
            status = (row.status or "draft").strip().lower()[:32] or "draft"
            raw = getattr(row, "checklist_json", None)
            existing_items = _normalize_checklist(raw)
            existing_titles = {str(x.get("title", "")).strip().lower() for x in existing_items}

        merged = list(existing_items)
        for it in DEFAULT_ITEMS:
            t = str(it["title"]).strip().lower()
            if t in existing_titles:
                continue
            merged.append(
                {
                    "id": str(uuid.uuid4()),
                    "title": str(it["title"]),
                    "done": bool(it["done"]),
                    "remind_at": it.get("remind_at"),
                }
            )
            existing_titles.add(t)

        low = plan_text.lower()
        if LAND_MARK not in low and MD_HEADER.strip():
            plan_text = MD_HEADER + (plan_text or "").lstrip()

    out = upsert_daily_plan(
        user_id=uid,
        for_date=for_d,
        plan_text=plan_text,
        status=status,
        checklist=merged,
    )
    if out is None:
        print("ERROR: upsert failed (database).", file=sys.stderr)
        return 1

    print("OK: daily plan updated for", email, "date", for_d.isoformat())
    print("  Checklist items:", len(out.get("checklist") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
