"""
Terminate idle client backends on the current database (pg_terminate_backend).

Loads ``DATABASE_URL`` from the project root ``.env``. Use when PostgreSQL returns
``FATAL: sorry, too many clients already`` from leaked idle pools or dev reloads.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.env_bootstrap import load_project_dotenv  # noqa: E402


def main() -> int:
    load_project_dotenv(root=ROOT)
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL is not set (check .env).", file=sys.stderr)
        return 1

    import psycopg2

    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pid, usename, application_name, state, client_addr
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND state = 'idle'
                  AND backend_type = 'client backend'
                """
            )
            targets = cur.fetchall()
            terminated = 0
            for row in targets:
                pid = row[0]
                cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
                if cur.fetchone()[0]:
                    terminated += 1
            print(f"Found {len(targets)} idle client backend(s); terminated {terminated}.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
