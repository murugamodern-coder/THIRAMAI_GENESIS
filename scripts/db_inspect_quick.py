"""One-off: print alembic_version and a few key tables (run from repo root)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from core.env_bootstrap import load_project_dotenv

load_project_dotenv(root=ROOT)

from core.database import get_database_url, normalize_database_url  # noqa: E402


def main() -> None:
    u = get_database_url()
    if not u:
        print("NO_DATABASE_URL")
        return
    e = create_engine(normalize_database_url(u))
    with e.connect() as c:
        try:
            v = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
            print("alembic_version:", v)
        except Exception as ex:
            print("alembic_version: ERROR", ex)
        q = text(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name IN (
              'inventory_items', 'jarvis_memory', 'jarvis_episodes', 'jarvis_facts',
              'jarvis_sessions', 'jarvis_session_turns', 'jarvis_proactive_alerts',
              'jarvis_proactive_feedback', 'jarvis_goals', 'jarvis_goal_subtasks',
              'jarvis_daily_agent_plans', 'jarvis_agent_action_log', 'jarvis_agent_event_queue',
              'personal_meetings', 'notifications', 'meetings', 'stock_movements', 'suppliers'
            )
            ORDER BY 1
            """
        )
        rows = c.execute(q).fetchall()
        print("key tables:", [r[0] for r in rows])
        n = c.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        ).scalar()
        print("public table count:", n)


if __name__ == "__main__":
    main()
