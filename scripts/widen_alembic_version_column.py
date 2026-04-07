"""One-shot: widen alembic_version.version_num so long revision IDs fit (VARCHAR(32) is too small)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
url = os.getenv("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL not set")
engine = create_engine(url, pool_pre_ping=True)
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))
    conn.commit()
print("OK: alembic_version.version_num -> VARCHAR(128)")
