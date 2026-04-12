"""
Life OS persistence: daily planner, health logs, personal reminders, personal vault crypto.

All rows are scoped by ``user_id`` (and business reads additionally by ``organization_id``).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.database import get_session_factory
from core.db.models import (
    DailyPlanner,
    EncNote,
    Habit,
    HabitLog,
    HealthLog,
    PersonalHealthMetric,
    PersonalMission,
    PersonalReminder,
    UserPersonalCrypto,
)
from services import personal_crypto as pc

# Spec: sleep / steps / mood; ``water`` = glasses count from legacy vault JSON; ``step`` accepted as alias of ``steps``.
ALLOWED_HEALTH_METRIC_TYPES = frozenset({"sleep", "steps", "step", "mood", "water"})
MISSION_OPEN_STATUSES = frozenset({"open", "in_progress"})


def _normalize_metric_type(name: str) -> str:
    t = (name or "").strip().lower()[:32]
    if t == "step":
        return "steps"
    return t


def server_vault_fernet_from_env() -> Fernet | None:
    """Fernet from ``VAULT_PASSPHRASE`` when set (min 8 chars). Used for vault → DB note migration and server-side enc_notes."""
    raw = (os.getenv("VAULT_PASSPHRASE") or "").strip()
    if len(raw) < 8:
        return None
    return pc.fernet_from_vault_passphrase(raw)


def _factory() -> sessionmaker[Session] | None:
    return get_session_factory()  # type: ignore[return-value]


def init_personal_vault(*, user_id: int, passphrase: str) -> tuple[bool, str]:
    """
    Create or rotate personal crypto row. Passphrase must be at least 8 characters.
    """
    uid = int(user_id)
    if uid <= 0:
        return False, "invalid user"
    if len((passphrase or "").strip()) < 8:
        return False, "passphrase must be at least 8 characters"
    salt = pc.new_salt()
    raw = pc.derive_raw_key(passphrase.strip(), salt)
    ver = pc.verifier_hash(raw)
    factory = _factory()
    if factory is None:
        return False, "database not configured"
    with factory() as session:
        with session.begin():
            row = session.get(UserPersonalCrypto, uid)
            if row is None:
                session.add(
                    UserPersonalCrypto(
                        user_id=uid,
                        salt=salt,
                        key_verifier_hash=ver,
                    )
                )
            else:
                row.salt = salt
                row.key_verifier_hash = ver
    return True, "ok"


def unlock_fernet(*, user_id: int, passphrase: str) -> Fernet | None:
    """Return Fernet for this user if passphrase matches stored verifier."""
    uid = int(user_id)
    if uid <= 0 or not (passphrase or "").strip():
        return None
    factory = _factory()
    if factory is None:
        return None
    with factory() as session:
        row = session.get(UserPersonalCrypto, uid)
        if row is None:
            return None
        raw = pc.derive_raw_key(passphrase.strip(), row.salt)
        if not pc.verify_raw_key(raw, row.key_verifier_hash):
            return None
        return pc.fernet_from_raw(raw)


def get_today_planner_row(session: Session, user_id: int, *, for_date: date | None = None) -> DailyPlanner | None:
    d = for_date or datetime.now(timezone.utc).date()
    stmt = select(DailyPlanner).where(DailyPlanner.user_id == int(user_id), DailyPlanner.for_date == d).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def get_health_for_day(session: Session, user_id: int, logged_on: date) -> HealthLog | None:
    stmt = select(HealthLog).where(HealthLog.user_id == int(user_id), HealthLog.logged_on == logged_on).limit(1)
    return session.execute(stmt).scalar_one_or_none()


def list_upcoming_reminders(session: Session, user_id: int, *, limit: int = 20) -> list[PersonalReminder]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(PersonalReminder)
        .where(
            PersonalReminder.user_id == int(user_id),
            PersonalReminder.done_at.is_(None),
            PersonalReminder.remind_at >= now,
        )
        .order_by(PersonalReminder.remind_at.asc())
        .limit(max(1, min(limit, 100)))
    )
    return list(session.execute(stmt).scalars().all())


def list_hub_reminders_sync(*, user_id: int, limit: int = 40) -> list[dict[str, Any]]:
    """Open reminders in a window (recent overdue → upcoming) for dashboard bell + notifications."""
    uid = int(user_id)
    lim = max(1, min(int(limit), 100))
    factory = _factory()
    if factory is None:
        return []
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=14)
    window_end = now + timedelta(days=90)
    with factory() as session:
        rows = session.execute(
            select(PersonalReminder)
            .where(
                PersonalReminder.user_id == uid,
                PersonalReminder.done_at.is_(None),
                PersonalReminder.remind_at >= window_start,
                PersonalReminder.remind_at <= window_end,
            )
            .order_by(PersonalReminder.remind_at.asc())
            .limit(lim)
        ).scalars().all()
        return [
            {
                "id": int(r.id),
                "title": r.title or "",
                "remind_at": r.remind_at.isoformat() if r.remind_at else None,
                "overdue": bool(r.remind_at and r.remind_at < now),
            }
            for r in rows
        ]


def decrypt_private_notes(
    cipher: bytes | None,
    *,
    fernet: Fernet | None,
) -> str:
    if not cipher or fernet is None:
        return ""
    out = pc.decrypt_utf8(fernet, cipher)
    return out or ""


def format_life_os_snapshot_markdown(
    *,
    user_id: int,
    organization_id: int,
    vault_passphrase: str | None,
    max_chars: int = 4000,
    use_cache: bool = True,
) -> str:
    """
    Markdown block for the brain: DB-backed planner, health, reminders + decrypted private fields when unlocked.

    Cached in Redis (5 min) when ``REDIS_URL`` is set and ``use_cache`` is True; cache key includes a
    fingerprint of the vault passphrase so ciphertext changes do not leak across passphrases.
    """
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0:
        return ""

    from core.redis_cache import cache_get_json, cache_set_json, snapshot_cache_ttl_sec

    pp_fp = hashlib.sha256((vault_passphrase or "").encode("utf-8")).hexdigest()[:16]
    cache_key = f"thiramai:cache:life_os:{uid}:{oid}:{pp_fp}:{max_chars}"
    if use_cache:
        hit = cache_get_json(cache_key)
        if isinstance(hit, dict) and "markdown" in hit:
            return str(hit["markdown"])

    factory = _factory()
    if factory is None:
        return "_Life OS database is not configured (DATABASE_URL)._"

    fernet = None
    if vault_passphrase and vault_passphrase.strip():
        fernet = unlock_fernet(user_id=uid, passphrase=vault_passphrase.strip())

    lines: list[str] = ["## Life OS (database — user-scoped)", f"- **user_id:** {uid}", ""]

    with factory() as session:
        today = datetime.now(timezone.utc).date()
        pl = get_today_planner_row(session, uid, for_date=today)
        if pl:
            lines.append(f"### Daily planner ({today.isoformat()})")
            lines.append(f"- **blocks (JSON slots):** `{str(pl.blocks)[:1200]}`")
            if pl.ai_flow_hint:
                lines.append(f"- **last AI flow hint:** {pl.ai_flow_hint[:800]}")
            if pl.private_notes_cipher:
                if fernet:
                    priv = decrypt_private_notes(pl.private_notes_cipher, fernet=fernet)
                    if priv:
                        lines.append(f"- **private notes (decrypted):** {priv[:1500]}")
                    else:
                        lines.append("- **private notes:** _(decryption failed — wrong passphrase?)_")
                else:
                    lines.append("- **private notes:** _(encrypted — provide vault passphrase to decrypt in chat)_")
            lines.append("")
        else:
            lines.append(f"### Daily planner ({today.isoformat()})\n- _(no row yet — user can create via API)_\n")

        hl = get_health_for_day(session, uid, today)
        if hl:
            lines.append("### Health log (today)")
            if hl.sleep_hours is not None:
                lines.append(f"- sleep_hours: {hl.sleep_hours}")
            if hl.water_glasses is not None:
                lines.append(f"- water_glasses: {hl.water_glasses}")
            if hl.stress_1_10 is not None:
                lines.append(f"- stress_1_10: {hl.stress_1_10}")
            if hl.reflection_cipher and hl.reflection_encrypted:
                if fernet:
                    ref = decrypt_private_notes(hl.reflection_cipher, fernet=fernet)
                    lines.append(f"- reflection (decrypted): {ref[:1200] if ref else '_(invalid cipher)_'}")
                else:
                    lines.append("- reflection: _(encrypted)_")
            lines.append("")
        else:
            lines.append("### Health log (today)\n- _(no entry)_\n")

        rems = list_upcoming_reminders(session, uid, limit=12)
        if rems:
            lines.append("### Personal reminders (upcoming)")
            for r in rems:
                ts = r.remind_at.isoformat() if r.remind_at else ""
                title = (r.title or "").strip() or "(no title)"
                if r.body_cipher and r.body_encrypted:
                    if fernet:
                        body = decrypt_private_notes(r.body_cipher, fernet=fernet) or "_(decrypt failed)_"
                        lines.append(f"- **{ts}** · {title} — {body[:400]}")
                    else:
                        lines.append(f"- **{ts}** · {title} — _(encrypted body)_")
                else:
                    lines.append(f"- **{ts}** · {title}")
            lines.append("")

    # Business signals (tenant)
    try:
        from services import approval_store
        from services.analytics_service import list_low_stock_alerts_sync

        pending = approval_store.list_pending(organization_id=oid)
        stockish = [p for p in pending if "stock" in (p.get("action_type") or "").lower() or "order" in (p.get("summary") or "").lower()][:8]
        if stockish:
            lines.append("### Business tasks (stock / orders — pending HITL)")
            for p in stockish:
                lines.append(f"- {p.get('action_type')}: {p.get('summary', '')[:200]}")
            lines.append("")
        low = list_low_stock_alerts_sync(oid, threshold=5)
        if low.get("ok") and int(low.get("count") or 0) > 0:
            lines.append("### Inventory pressure")
            lines.append(f"- **{low['count']} SKUs** below low-stock threshold.")
            for it in (low.get("items") or [])[:6]:
                if isinstance(it, dict):
                    lines.append(f"- `{it.get('sku_name')}` qty **{it.get('quantity')}**")
            lines.append("")
    except Exception:
        pass

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 40] + "\n\n_[… Life OS block clipped …]_"
    if use_cache and factory is not None:
        cache_set_json(cache_key, {"markdown": text}, ttl_sec=snapshot_cache_ttl_sec())
    return text


def upsert_daily_planner_blocks(
    *,
    user_id: int,
    for_date: date,
    blocks: list[Any],
) -> bool:
    factory = _factory()
    if factory is None:
        return False
    uid = int(user_id)
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(DailyPlanner).where(DailyPlanner.user_id == uid, DailyPlanner.for_date == for_date).limit(1)
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    DailyPlanner(
                        user_id=uid,
                        for_date=for_date,
                        blocks=list(blocks) if isinstance(blocks, list) else [],
                    )
                )
            else:
                row.blocks = list(blocks) if isinstance(blocks, list) else []
    return True


def save_ai_flow_hint(*, user_id: int, for_date: date, hint: str) -> None:
    factory = _factory()
    if factory is None:
        return
    uid = int(user_id)
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(DailyPlanner).where(DailyPlanner.user_id == uid, DailyPlanner.for_date == for_date).limit(1)
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    DailyPlanner(
                        user_id=uid,
                        for_date=for_date,
                        blocks=[],
                        ai_flow_hint=(hint or "")[:8000],
                    )
                )
            else:
                row.ai_flow_hint = (hint or "")[:8000]


def upsert_health_metrics(
    *,
    user_id: int,
    logged_on: date,
    sleep_hours: Decimal | None = None,
    water_glasses: int | None = None,
    stress_1_10: int | None = None,
    reflection_plain: str | None = None,
    fernet: Fernet | None = None,
) -> tuple[bool, str]:
    factory = _factory()
    if factory is None:
        return False, "no database"
    uid = int(user_id)
    ref_cipher: bytes | None = None
    ref_enc = False
    if reflection_plain and reflection_plain.strip():
        if fernet is None:
            return False, "vault passphrase required to store encrypted reflection"
        ref_cipher = pc.encrypt_utf8(fernet, reflection_plain.strip())
        ref_enc = True
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(HealthLog).where(HealthLog.user_id == uid, HealthLog.logged_on == logged_on).limit(1)
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    HealthLog(
                        user_id=uid,
                        logged_on=logged_on,
                        sleep_hours=sleep_hours,
                        water_glasses=water_glasses,
                        stress_1_10=stress_1_10,
                        reflection_cipher=ref_cipher,
                        reflection_encrypted=ref_enc,
                    )
                )
            else:
                if sleep_hours is not None:
                    row.sleep_hours = sleep_hours
                if water_glasses is not None:
                    row.water_glasses = water_glasses
                if stress_1_10 is not None:
                    row.stress_1_10 = stress_1_10
                if ref_cipher is not None:
                    row.reflection_cipher = ref_cipher
                    row.reflection_encrypted = ref_enc
    return True, "ok"


def add_personal_reminder(
    *,
    user_id: int,
    remind_at: datetime,
    title: str,
    body_plain: str | None = None,
    fernet: Fernet | None = None,
) -> tuple[bool, str]:
    factory = _factory()
    if factory is None:
        return False, "no database"
    uid = int(user_id)
    cipher: bytes | None = None
    enc = False
    if body_plain and body_plain.strip():
        if fernet is None:
            return False, "vault passphrase required for encrypted reminder body"
        cipher = pc.encrypt_utf8(fernet, body_plain.strip())
        enc = True
    with factory() as session:
        with session.begin():
            session.add(
                PersonalReminder(
                    user_id=uid,
                    remind_at=remind_at,
                    title=(title or "")[:500],
                    body_cipher=cipher,
                    body_encrypted=enc,
                )
            )
    return True, "ok"


def _utc_day_start(dt: datetime | None = None) -> datetime:
    d = (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def sync_executive_vault_json_to_postgres(*, user_id: int) -> dict[str, int]:
    """
    Import ``vault/agenda_state.json`` + ``user_profile.json`` (executive_core) into PostgreSQL.

    Idempotent: uses ``source_ref`` / title matching to avoid duplicate missions and habits.
    """
    import executive_core as ec

    uid = int(user_id)
    counts = {"habits": 0, "missions": 0, "health_metrics": 0, "enc_notes": 0}
    if uid <= 0:
        return counts
    factory = _factory()
    if factory is None:
        return counts

    agenda = ec.load_agenda_state()
    profile = ec.load_user_profile()
    now = datetime.now(timezone.utc)
    day_start = _utc_day_start(now)
    server_fernet = server_vault_fernet_from_env()

    def _upsert_metric_today(metric_type: str, value: str) -> None:
        nonlocal counts
        mt = _normalize_metric_type(metric_type)
        row = session.execute(
            select(PersonalHealthMetric).where(
                PersonalHealthMetric.user_id == uid,
                PersonalHealthMetric.metric_type == mt,
                PersonalHealthMetric.recorded_at >= day_start,
            ).limit(1)
        ).scalar_one_or_none()
        if row is None:
            session.add(
                PersonalHealthMetric(
                    user_id=uid,
                    metric_type=mt,
                    value=value,
                    recorded_at=now,
                )
            )
            counts["health_metrics"] += 1
        elif row.value != value:
            row.value = value

    with factory() as session:
        with session.begin():
            h = agenda.get("health_today") or {}
            if h.get("sleep_hours") is not None:
                _upsert_metric_today("sleep", str(h["sleep_hours"]))
            if h.get("water_glasses") is not None:
                _upsert_metric_today("water", str(int(h["water_glasses"])))
            if h.get("stress_1_10") is not None:
                _upsert_metric_today("mood", str(int(h["stress_1_10"])))
            if h.get("steps") is not None:
                _upsert_metric_today("steps", str(int(h["steps"])))

            if server_fernet is not None:
                raw_notes = profile.get("life_os_plain_notes")
                if isinstance(raw_notes, list):
                    for item in raw_notes:
                        text = ""
                        user_cat = "vault"
                        if isinstance(item, str):
                            text = item.strip()
                        elif isinstance(item, dict):
                            text = (item.get("text") or item.get("body") or "").strip()
                            user_cat = (item.get("category") or "vault").strip()[:48] or "vault"
                        if not text:
                            continue
                        payload = json.dumps({"category": user_cat, "body": text}, ensure_ascii=False)
                        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
                        dedupe_cat = f"vi_{digest}"[:64]
                        n_existing = session.execute(
                            select(func.count())
                            .select_from(EncNote)
                            .where(EncNote.user_id == uid, EncNote.category == dedupe_cat)
                        ).scalar_one()
                        if int(n_existing or 0) > 0:
                            continue
                        blob = pc.encrypt_utf8(server_fernet, payload)
                        session.add(EncNote(user_id=uid, encrypted_content=blob, category=dedupe_cat))
                        counts["enc_notes"] += 1

            for t in agenda.get("tasks") or []:
                if not isinstance(t, dict):
                    continue
                title = (t.get("title") or "").strip()
                if not title:
                    continue
                tid = t.get("id")
                ref = f"agenda_task:{tid}" if tid is not None else None
                stmt = select(PersonalMission).where(PersonalMission.user_id == uid)
                if ref:
                    stmt = stmt.where(PersonalMission.source_ref == ref)
                else:
                    stmt = stmt.where(PersonalMission.title == title, PersonalMission.source_ref.is_(None))
                existing = session.execute(stmt.limit(1)).scalar_one_or_none()
                st = "done" if t.get("done") else "open"
                cat = (t.get("category") or "").strip()
                if existing:
                    existing.title = title[:2000]
                    existing.description = cat[:8000] if cat else existing.description
                    existing.status = st
                else:
                    session.add(
                        PersonalMission(
                            user_id=uid,
                            title=title[:2000],
                            description=cat[:8000] if cat else None,
                            status=st,
                            source_ref=ref,
                        )
                    )
                    counts["missions"] += 1

            for item in profile.get("personal_habits") or []:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                if not title:
                    continue
                gf = (item.get("goal_frequency") or "daily").strip()[:128]
                exists = session.execute(
                    select(Habit).where(Habit.user_id == uid, Habit.title == title).limit(1)
                ).scalar_one_or_none()
                if exists is None:
                    session.add(
                        Habit(
                            user_id=uid,
                            title=title[:2000],
                            goal_frequency=gf or "daily",
                            is_active=True,
                        )
                    )
                    counts["habits"] += 1

    return counts


def _habit_completed_today(session: Session, habit_id: int, *, day_start: datetime) -> bool:
    q = session.execute(
        select(func.count())
        .select_from(HabitLog)
        .where(
            HabitLog.habit_id == int(habit_id),
            HabitLog.status == "completed",
            HabitLog.completed_at >= day_start,
        )
    ).scalar_one()
    return int(q or 0) > 0


def _update_streak_after_completion(
    session: Session,
    habit: Habit,
    when: datetime,
    *,
    last_completed_before: HabitLog | None,
) -> None:
    """``last_completed_before`` must be the most recent completed log *before* inserting today's row (avoids autoflush seeing the new row)."""
    today = when.astimezone(timezone.utc).date()
    last = last_completed_before
    if last is None:
        habit.streak_count = 1
        return
    ld = last.completed_at.astimezone(timezone.utc).date()
    if ld == today:
        return
    if ld == today - timedelta(days=1):
        habit.streak_count = int(habit.streak_count or 0) + 1
    else:
        habit.streak_count = 1


def log_habit_check_in(
    *,
    user_id: int,
    habit_id: int,
    status: str = "completed",
) -> tuple[bool, str]:
    uid = int(user_id)
    hid = int(habit_id)
    st = (status or "completed").strip().lower()[:32]
    if uid <= 0:
        return False, "invalid user"
    factory = _factory()
    if factory is None:
        return False, "database not configured"
    now = datetime.now(timezone.utc)
    day_start = _utc_day_start(now)
    with factory() as session:
        with session.begin():
            habit = session.get(Habit, hid)
            if habit is None or int(habit.user_id) != uid:
                return False, "habit not found"
            if not habit.is_active:
                return False, "habit inactive"
            if st == "completed" and _habit_completed_today(session, hid, day_start=day_start):
                return True, "already_logged_today"
            last_before = session.execute(
                select(HabitLog)
                .where(HabitLog.habit_id == hid, HabitLog.status == "completed")
                .order_by(HabitLog.completed_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            session.add(HabitLog(habit_id=hid, completed_at=now, status=st))
            if st == "completed":
                _update_streak_after_completion(session, habit, now, last_completed_before=last_before)
            elif st == "skipped":
                habit.streak_count = 0
    return True, "ok"


def upsert_personal_mission(
    *,
    user_id: int,
    mission_id: int | None = None,
    title: str,
    description: str | None = None,
    deadline: datetime | None = None,
    status: str = "open",
    progress_percent: int | None = None,
    priority: str | None = None,
) -> tuple[bool, str, int | None, bool]:
    """
    Create or update a personal mission. When ``mission_id`` is set, updates that row if it belongs to the user.

    Returns ``(ok, message, mission_id, created)`` where ``created`` is True only on insert.
    """
    uid = int(user_id)
    if uid <= 0:
        return False, "invalid user", None, False
    factory = _factory()
    if factory is None:
        return False, "database not configured", None, False
    st = (status or "open").strip().lower()[:32]
    ttl = (title or "").strip()[:2000]
    if not ttl:
        return False, "title required", None, False
    pr = (priority or "P2").strip().upper()[:8]
    if pr not in ("P1", "P2", "P3"):
        pr = "P2"
    mid_in = int(mission_id) if mission_id is not None and int(mission_id) > 0 else None
    with factory() as session:
        with session.begin():
            if mid_in is not None:
                row = session.get(PersonalMission, mid_in)
                if row is None or int(row.user_id) != uid:
                    return False, "mission not found", None, False
                row.title = ttl
                if description is not None:
                    row.description = (description or "").strip()[:8000] or None
                if deadline is not None:
                    row.deadline = deadline
                row.status = st
                if progress_percent is not None:
                    pp = max(0, min(100, int(progress_percent)))
                    row.progress_percent = pp
                if priority is not None:
                    row.priority = pr
                return True, "ok", int(row.id), False
            row = PersonalMission(
                user_id=uid,
                title=ttl,
                description=(description or "").strip()[:8000] if description else None,
                deadline=deadline,
                status=st,
                priority=pr,
                progress_percent=max(0, min(100, int(progress_percent))) if progress_percent is not None else None,
            )
            session.add(row)
            session.flush()
            return True, "ok", int(row.id), True
    return False, "unknown", None, False


def create_personal_mission(
    *,
    user_id: int,
    title: str,
    description: str | None = None,
    deadline: datetime | None = None,
    status: str = "open",
) -> tuple[bool, str, int | None]:
    ok, msg, mid, _ = upsert_personal_mission(
        user_id=user_id,
        mission_id=None,
        title=title,
        description=description,
        deadline=deadline,
        status=status,
        priority=None,
    )
    return ok, msg, mid


def add_encrypted_note(
    *,
    user_id: int,
    plaintext: str,
    category: str,
    fernet: Fernet,
) -> tuple[bool, str, int | None]:
    uid = int(user_id)
    if uid <= 0:
        return False, "invalid user", None
    pt = (plaintext or "").strip()
    if not pt:
        return False, "empty note", None
    factory = _factory()
    if factory is None:
        return False, "database not configured", None
    blob = pc.encrypt_utf8(fernet, pt)
    cat = (category or "general").strip()[:64] or "general"
    with factory() as session:
        with session.begin():
            row = EncNote(user_id=uid, encrypted_content=blob, category=cat)
            session.add(row)
            session.flush()
            return True, "ok", int(row.id)
    return False, "unknown", None


def build_life_dashboard_payload(*, user_id: int) -> dict[str, Any]:
    """Structured summary for ``GET /life/dashboard``."""
    uid = int(user_id)
    out: dict[str, Any] = {
        "habits": [],
        "habits_pending_today": 0,
        "health_today": [],
        "missions_open": [],
        "sync_counts": {},
    }
    if uid <= 0:
        return out
    factory = _factory()
    if factory is None:
        return out

    out["sync_counts"] = sync_executive_vault_json_to_postgres(user_id=uid)
    now = datetime.now(timezone.utc)
    day_start = _utc_day_start(now)

    with factory() as session:
        habits = session.execute(
            select(Habit).where(Habit.user_id == uid, Habit.is_active.is_(True)).order_by(Habit.title.asc())
        ).scalars().all()
        pending = 0
        for h in habits:
            done_today = _habit_completed_today(session, int(h.id), day_start=day_start)
            if not done_today:
                pending += 1
            out["habits"].append(
                {
                    "id": int(h.id),
                    "title": h.title,
                    "goal_frequency": h.goal_frequency,
                    "streak_count": int(h.streak_count),
                    "completed_today": done_today,
                }
            )
        out["habits_pending_today"] = pending

        metrics = session.execute(
            select(PersonalHealthMetric)
            .where(
                PersonalHealthMetric.user_id == uid,
                PersonalHealthMetric.recorded_at >= day_start,
            )
            .order_by(PersonalHealthMetric.recorded_at.desc())
        ).scalars().all()
        out["health_today"] = [
            {"metric_type": m.metric_type, "value": m.value, "recorded_at": m.recorded_at.isoformat()}
            for m in metrics
        ]

        hl = get_health_for_day(session, uid, now.date())
        if hl:
            out["legacy_health_log"] = {
                "sleep_hours": float(hl.sleep_hours) if hl.sleep_hours is not None else None,
                "water_glasses": hl.water_glasses,
                "stress_1_10": hl.stress_1_10,
            }

        missions = session.execute(
            select(PersonalMission)
            .where(PersonalMission.user_id == uid, PersonalMission.status.in_(MISSION_OPEN_STATUSES))
            .order_by(PersonalMission.deadline.asc().nulls_last(), PersonalMission.id.desc())
            .limit(20)
        ).scalars().all()
        out["missions_open"] = [
            {
                "id": int(m.id),
                "title": m.title,
                "deadline": m.deadline.isoformat() if m.deadline else None,
                "status": m.status,
                "progress_percent": int(m.progress_percent)
                if getattr(m, "progress_percent", None) is not None
                else None,
            }
            for m in missions[:8]
        ]

    return out


def format_jarvis_dual_context_markdown(
    *,
    user_id: int,
    organization_id: int,
    vault_passphrase: str | None = None,
    max_chars: int = 2800,
) -> str:
    """
    Compact **business + personal** snapshot for every council turn (Sovereign JARVIS).

    Enables answers like: pending bills in one org + habits not logged today.
    """
    uid = int(user_id)
    oid = int(organization_id)
    if uid <= 0:
        return ""

    lines = [
        "## JARVIS unified snapshot (business + personal)",
        f"- **Active organization_id:** {oid}",
        "",
    ]

    try:
        from services import approval_store
        from services.analytics_service import compute_dashboard_summary_sync, list_low_stock_alerts_sync

        pending = approval_store.list_pending(organization_id=oid)
        inv_pending = [p for p in pending if (p.get("action_type") or "") == "issue_invoice"][:6]
        if inv_pending:
            lines.append(f"### Business — **{len(inv_pending)}** pending invoice / billing approvals (HITL)")
            for p in inv_pending[:4]:
                lines.append(f"- {p.get('summary', '')[:220]}")
        else:
            lines.append("### Business — no pending invoice approvals in queue.")
        lines.append("")
        low = list_low_stock_alerts_sync(oid, threshold=5)
        if low.get("ok") and int(low.get("count") or 0) > 0:
            lines.append(f"### Business — low stock: **{low['count']}** SKU(s) below threshold.")
        else:
            lines.append("### Business — low stock: none flagged.")
        lines.append("")
        fin = compute_dashboard_summary_sync(oid, low_stock_threshold=5)
        if fin.get("ok"):
            rt = (fin.get("revenue_inr") or {}).get("today") or "0"
            lines.append(f"- **Revenue today (INR, bills):** {rt}")
        lines.append("")
    except Exception:
        lines.append("_Business snapshot unavailable._\n")

    dash = build_life_dashboard_payload(user_id=uid)
    lines.append("### Personal — habits (today)")
    if dash.get("habits"):
        pending_n = int(dash.get("habits_pending_today") or 0)
        lines.append(f"- **{pending_n}** active habit(s) not yet completed today.")
        for h in dash["habits"][:10]:
            if not h.get("completed_today"):
                lines.append(f"- [ ] **{h.get('title')}** (streak {h.get('streak_count', 0)}, {h.get('goal_frequency')})")
        done_any = [h for h in dash["habits"] if h.get("completed_today")]
        if done_any:
            lines.append("- Completed today: " + ", ".join(h["title"] for h in done_any[:6]))
    else:
        lines.append("- _(No habits yet — sync vault or create via Life OS.)_")
    lines.append("")

    lines.append("### Personal — health (today)")
    ht = dash.get("health_today") or []
    leg = dash.get("legacy_health_log")
    has_legacy = (
        isinstance(leg, dict)
        and any(leg.get(k) is not None for k in ("sleep_hours", "water_glasses", "stress_1_10"))
    )
    if ht:
        for row in ht[:8]:
            lines.append(f"- **{row.get('metric_type')}:** {row.get('value')}")
    if has_legacy:
        parts = [
            f"{k}={leg[k]}"
            for k in ("sleep_hours", "water_glasses", "stress_1_10")
            if leg.get(k) is not None
        ]
        lines.append("- **legacy daily health_log:** " + ", ".join(parts))
    if not ht and not has_legacy:
        lines.append("- _(No health metrics logged today.)_")
    lines.append("")

    lines.append("### Personal — open missions / goals")
    mo = dash.get("missions_open") or []
    if mo:
        for m in mo[:6]:
            dl = m.get("deadline") or "no deadline"
            lines.append(f"- **{m.get('title')}** — deadline: {dl}")
    else:
        lines.append("- _(No open personal missions.)_")

    if vault_passphrase and vault_passphrase.strip():
        lines.append("")
        lines.append(
            "_Personal vault passphrase present — extended Life OS blocks may include decrypted planner fields._"
        )

    lines.append("")
    lines.append("### JARVIS correlation directive")
    lines.append(
        "When **business** signals (revenue, pending bills, low stock) and **personal** signals (sleep, steps, mood, habits) "
        "point in different directions, answer in **one** coherent sentence (e.g. strong billing activity but poor sleep → suggest "
        "wrapping up and resting after urgent bills)."
    )

    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        return text[: max_chars - 40] + "\n\n_[… clipped …]_"
    return text
