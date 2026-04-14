"""Unit tests for smart meeting heuristics and ICS (no DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.personal_meeting_intelligence import (
    build_meeting_ics,
    find_overlapping_meeting_ids,
    ics_escape,
    suggest_duration_and_agenda,
)


def test_suggest_client_duration_and_agenda() -> None:
    d = suggest_duration_and_agenda("client")
    assert d["suggested_duration_minutes"] == 30
    assert "needs" in d["agenda_template"].lower() or "intro" in d["agenda_template"].lower()


def test_suggest_unknown_defaults() -> None:
    d = suggest_duration_and_agenda("unknown_xyz_type")
    assert d["suggested_duration_minutes"] == 45
    assert "agenda" in d["agenda_template"].lower()


def test_ics_escape_special_chars() -> None:
    assert ics_escape("a;b,c\\d\ne") == "a\\;b\\,c\\\\d\\ne"


def test_build_meeting_ics_vevent() -> None:
    start = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)
    m = SimpleNamespace(
        id=42,
        title="Client sync",
        agenda="Q1 plan",
        notes=None,
        location_name="Zoom",
        scheduled_at=start,
        duration_minutes=30,
    )
    s = build_meeting_ics(m)  # type: ignore[arg-type]
    assert "BEGIN:VCALENDAR" in s
    assert "BEGIN:VEVENT" in s
    assert "END:VEVENT" in s
    assert "END:VCALENDAR" in s
    assert "thiramai-meeting-42@" in s
    assert "DTSTART:20260115T143000Z" in s
    assert "DTEND:20260115T150000Z" in s


def test_find_overlapping_meeting_ids() -> None:
    """Overlap logic with a fake session that returns fixed rows."""

    class _Row:
        def __init__(self, mid: int, start: datetime, dur: int) -> None:
            self.id = mid
            self.scheduled_at = start
            self.duration_minutes = dur

    base = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    # Candidate: 10:00–11:00
    # A: 09:30–10:30 overlaps
    # B: 11:00–12:00 touches at boundary — [start, end) vs [ms, mend): start < mend and ms < end → 10:00 < 12:00 and 11:00 < 11:00 is False for second? ms < end: 11:00 < 11:00 False. Good no overlap.
    # C: 10:45–11:15 overlaps
    rows = [
        _Row(1, base - timedelta(minutes=30), 60),
        _Row(2, base + timedelta(hours=1), 60),
        _Row(3, base + timedelta(minutes=45), 30),
    ]

    class _Exec:
        def __init__(self, r: list) -> None:
            self._r = r

        def scalars(self) -> "_Scalars":
            return _Scalars(self._r)

    class _Scalars:
        def __init__(self, r: list) -> None:
            self._r = r

        def all(self) -> list:
            return self._r

    class _SessAll:
        def execute(self, _stmt) -> _Exec:
            return _Exec(rows)

    class _SessExclude3:
        """Mimic SQL excluding id=3 (self-update case)."""

        def execute(self, _stmt) -> _Exec:
            return _Exec([r for r in rows if r.id != 3])

    cids = find_overlapping_meeting_ids(
        _SessAll(),  # type: ignore[arg-type]
        user_id=1,
        organization_id=1,
        scheduled_at=base,
        duration_minutes=60,
        exclude_meeting_id=None,
    )
    assert cids == [1, 3]

    cids_ex = find_overlapping_meeting_ids(
        _SessExclude3(),  # type: ignore[arg-type]
        user_id=1,
        organization_id=1,
        scheduled_at=base,
        duration_minutes=60,
        exclude_meeting_id=3,
    )
    assert cids_ex == [1]
