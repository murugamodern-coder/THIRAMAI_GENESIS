"""Reverse the last Jarvis tool batch (soft delete / cancel where supported)."""

from __future__ import annotations

import logging
from typing import Any

from core.database import get_session_factory
from core.db.models import Habit, PersonalExpense, PersonalMeeting, PersonalMission
from services.google_calendar_integration_service import delete_calendar_event

_log = logging.getLogger("thiramai.jarvis_undo")


def apply_undo_ops(*, user_id: int, ops: list[dict[str, Any]]) -> tuple[bool, str]:
    """Apply undo operations in reverse order (last action undone first)."""
    uid = int(user_id)
    factory = get_session_factory()
    if factory is None:
        return False, "database not configured"
    for op in reversed(ops):
        kind = str(op.get("kind") or "")
        if kind == "mission_cancel":
            mid = int(op.get("id") or 0)
            if mid <= 0:
                continue
            with factory() as session:
                with session.begin():
                    row = session.get(PersonalMission, mid)
                    if row is None or int(row.user_id) != uid:
                        continue
                    row.status = "cancelled"
        elif kind == "expense_delete":
            eid = int(op.get("id") or 0)
            if eid <= 0:
                continue
            with factory() as session:
                with session.begin():
                    row = session.get(PersonalExpense, eid)
                    if row is None or int(row.user_id) != uid:
                        continue
                    session.delete(row)
        elif kind == "meeting_cancel":
            mid = int(op.get("id") or 0)
            if mid <= 0:
                continue
            gid_s = ""
            with factory() as session:
                with session.begin():
                    row = session.get(PersonalMeeting, mid)
                    if row is None or int(row.user_id) != uid:
                        continue
                    gid_s = (getattr(row, "google_event_id", None) or op.get("google_event_id") or "")
                    gid_s = str(gid_s).strip()
                    row.status = "cancelled"
                    row.google_event_id = None
            if gid_s:
                try:
                    delete_calendar_event(user_id=uid, event_id=gid_s)
                except Exception:
                    _log.exception("undo: google delete failed")
        elif kind == "habit_deactivate":
            hid = int(op.get("id") or 0)
            if hid <= 0:
                continue
            with factory() as session:
                with session.begin():
                    row = session.get(Habit, hid)
                    if row is None or int(row.user_id) != uid:
                        continue
                    row.is_active = False
        else:
            _log.debug("unknown undo kind %s", kind)
    return True, "Undid last Jarvis action(s)."


def meeting_undo_payload(meeting_id: int, google_event_id: str | None) -> dict[str, Any]:
    return {
        "kind": "meeting_cancel",
        "id": int(meeting_id),
        "google_event_id": (google_event_id or "").strip() or None,
    }
