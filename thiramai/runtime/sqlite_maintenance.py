"""Integrity check, timestamped backup, and optional restore for goal-jobs SQLite."""

from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

from thiramai.config import DATA_DIR, THIRAMAI_SQLITE_BACKUP_INTERVAL_SEC
from thiramai.runtime.sqlite_job_store import ensure_schema, jobs_database_path

_backup_thread: threading.Thread | None = None
_backup_stop = threading.Event()


def _integrity_ok(path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(path), timeout=10.0)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and str(row[0]).lower() == "ok"
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return False


def backup_jobs_database() -> Path | None:
    """Copy ``goal_jobs.sqlite`` to ``data/backups/goal_jobs_YYYYMMDD_HHMMSS.sqlite``."""
    ensure_schema()
    src = jobs_database_path()
    if not src.is_file():
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    dest_dir = DATA_DIR / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"goal_jobs_{ts}.sqlite"
    try:
        shutil.copy2(src, dest)
        return dest
    except OSError:
        return None


def restore_latest_backup_if_corrupt() -> bool:
    """
    If the live DB fails integrity_check, replace it from the newest backup file (if any).
    Returns True when a restore was attempted (caller should reload jobs from disk).
    """
    src = jobs_database_path()
    if _integrity_ok(src):
        return False
    backup_dir = DATA_DIR / "backups"
    if not backup_dir.is_dir():
        return False
    candidates = sorted(backup_dir.glob("goal_jobs_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    for cand in candidates:
        if _integrity_ok(cand):
            try:
                shutil.copy2(cand, src)
                return True
            except OSError:
                continue
    return False


def ensure_jobs_database_healthy() -> None:
    """Run on API startup: restore from backup if corrupt, then fresh backup snapshot."""
    restore_latest_backup_if_corrupt()
    if _integrity_ok(jobs_database_path()):
        backup_jobs_database()


def _backup_loop(interval_sec: float) -> None:
    while not _backup_stop.wait(timeout=interval_sec):
        try:
            if _integrity_ok(jobs_database_path()):
                backup_jobs_database()
        except Exception:
            pass


def start_optional_backup_scheduler() -> None:
    global _backup_thread
    sec = float(THIRAMAI_SQLITE_BACKUP_INTERVAL_SEC or 0)
    if sec <= 0:
        return
    if _backup_thread and _backup_thread.is_alive():
        return
    _backup_stop.clear()
    _backup_thread = threading.Thread(
        target=_backup_loop,
        args=(max(60.0, sec),),
        name="thiramai-sqlite-backup",
        daemon=True,
    )
    _backup_thread.start()


def stop_backup_scheduler() -> None:
    _backup_stop.set()
