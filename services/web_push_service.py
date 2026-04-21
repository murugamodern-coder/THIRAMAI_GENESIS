"""
Web Push (VAPID) — subscribe/unsubscribe, send payloads, prune dead endpoints.

Env:
  THIRAMAI_VAPID_PUBLIC_KEY   — base64url-encoded P-256 public key (65-byte uncompressed point)
  THIRAMAI_VAPID_PRIVATE_KEY — PEM PKCS8 private key (or inline PEM newlines as \\n)
  THIRAMAI_VAPID_SUBJECT     — mailto:you@domain.com or https://your-app (required by spec)
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from core.database import get_session_factory
from core.db.models import PersonalLoan, PushSubscription, User

_log = logging.getLogger("thiramai.web_push")

_MAX_RETRIES = 3


def _command_center_shell(fragment: str) -> str:
    from core.settings import get_settings

    return get_settings().command_center_shell_url(fragment)
_RETRY_DELAY_SEC = 0.6
_memory_dedupe_expiry: dict[str, float] = {}


def vapid_configured() -> bool:
    pub = (os.getenv("THIRAMAI_VAPID_PUBLIC_KEY") or "").strip()
    priv = (os.getenv("THIRAMAI_VAPID_PRIVATE_KEY") or "").strip()
    subj = (os.getenv("THIRAMAI_VAPID_SUBJECT") or "").strip()
    return bool(pub and priv and subj)


def vapid_public_key_b64u() -> str | None:
    k = (os.getenv("THIRAMAI_VAPID_PUBLIC_KEY") or "").strip()
    return k or None


def _private_key_pem() -> str:
    raw = (os.getenv("THIRAMAI_VAPID_PRIVATE_KEY") or "").strip()
    if "BEGIN" in raw:
        return raw.replace("\\n", "\n")
    return raw


def _vapid_subject() -> str:
    return (os.getenv("THIRAMAI_VAPID_SUBJECT") or "mailto:support@thiramai.local").strip()


def _subscription_info(row: PushSubscription) -> dict[str, Any]:
    keys = row.keys_json if isinstance(row.keys_json, dict) else {}
    return {
        "endpoint": row.endpoint,
        "keys": {
            "p256dh": str(keys.get("p256dh") or ""),
            "auth": str(keys.get("auth") or ""),
        },
    }




def _send_one(
    subscription_info: dict[str, Any],
    payload_obj: dict[str, Any],
    *,
    ttl: int = 86400,
) -> tuple[bool, int | None, str | None]:
    """Returns (ok, http_status, error_message)."""
    if not vapid_configured():
        return False, None, "vapid_not_configured"
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        _log.warning("pywebpush not installed")
        return False, None, "pywebpush_missing"

    data = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
    vapid_claims = {"sub": _vapid_subject()}
    last_err: str | None = None
    last_status: int | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            webpush(
                subscription_info=subscription_info,
                data=data.encode("utf-8"),
                vapid_private_key=_private_key_pem(),
                vapid_claims=vapid_claims,
                ttl=ttl,
            )
            return True, 201, None
        except WebPushException as e:
            last_err = str(e) or "WebPushException"
            resp = getattr(e, "response", None)
            last_status = getattr(resp, "status_code", None) if resp is not None else None
            if last_status is None and resp is not None:
                last_status = getattr(resp, "status", None)
            if last_status in (404, 410):
                return False, last_status, last_err
            if last_status is not None and 500 <= int(last_status) < 600 and attempt + 1 < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SEC * (attempt + 1))
                continue
            if attempt + 1 < _MAX_RETRIES and last_status is None:
                time.sleep(_RETRY_DELAY_SEC * (attempt + 1))
                continue
            return False, last_status, last_err
        except Exception as e:
            last_err = str(e) or type(e).__name__
            if attempt + 1 < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SEC * (attempt + 1))
                continue
            return False, last_status, last_err
    return False, last_status, last_err


def send_payload_to_user(*, user_id: int, payload: dict[str, Any], ttl: int = 86400) -> dict[str, Any]:
    """
    Send JSON payload to all push endpoints for user.
    Payload is shown by the service worker (title, body, tag, data).
    """
    uid = int(user_id)
    if uid <= 0 or not vapid_configured():
        return {"ok": True, "sent": 0, "skipped": True, "reason": "no_vapid_or_user"}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "sent": 0, "error": "no_database"}
    sent = 0
    dead: list[int] = []
    errors: list[str] = []
    with factory() as session:
        rows = list(
            session.execute(select(PushSubscription).where(PushSubscription.user_id == uid)).scalars().all()
        )
        for row in rows:
            info = _subscription_info(row)
            if not info["keys"].get("p256dh") or not info["keys"].get("auth"):
                dead.append(int(row.id))
                errors.append(f"sub_{row.id}:missing_keys")
                continue
            ok, status, err = _send_one(info, payload, ttl=ttl)
            if ok:
                sent += 1
                _log.info("web_push sent user=%s sub_id=%s", uid, row.id)
            else:
                _log.warning(
                    "web_push fail user=%s sub_id=%s status=%s err=%s",
                    uid,
                    row.id,
                    status,
                    err,
                )
                if status in (404, 410):
                    dead.append(int(row.id))
                elif err:
                    errors.append(f"sub_{row.id}:{err}"[:200])
        if dead:
            with session.begin():
                for sid in dead:
                    session.execute(delete(PushSubscription).where(PushSubscription.id == int(sid)))
    return {"ok": True, "sent": sent, "removed_invalid": len(dead), "errors": errors[:10]}


def save_subscription_sync(*, user_id: int, endpoint: str, keys: dict[str, Any]) -> tuple[bool, str]:
    ep = (endpoint or "").strip()
    if not ep:
        return False, "endpoint required"
    p256 = str(keys.get("p256dh") or "").strip()
    au = str(keys.get("auth") or "").strip()
    if not p256 or not au:
        return False, "keys.p256dh and keys.auth required"
    uid = int(user_id)
    if uid <= 0:
        return False, "invalid user"
    factory = get_session_factory()
    if factory is None:
        return False, "database not configured"
    keys_clean = {"p256dh": p256, "auth": au}
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(PushSubscription).where(PushSubscription.endpoint == ep)
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    PushSubscription(
                        user_id=uid,
                        endpoint=ep,
                        keys_json=keys_clean,
                    )
                )
            else:
                row.user_id = uid
                row.keys_json = keys_clean
    return True, "ok"


def delete_subscription_sync(*, user_id: int, endpoint: str) -> tuple[bool, str]:
    ep = (endpoint or "").strip()
    uid = int(user_id)
    if not ep or uid <= 0:
        return False, "endpoint and user required"
    factory = get_session_factory()
    if factory is None:
        return False, "database not configured"
    with factory() as session:
        with session.begin():
            r = session.execute(
                select(PushSubscription).where(
                    PushSubscription.user_id == uid,
                    PushSubscription.endpoint == ep,
                )
            ).scalar_one_or_none()
            if r is None:
                return True, "not_found"
            session.delete(r)
    return True, "ok"


def _payload_meeting_soon(
    *,
    meeting_id: int,
    title: str,
    minutes_until: int,
    scheduled_at_iso: str,
) -> dict[str, Any]:
    t = (title or "Meeting").strip()[:120]
    return {
        "title": "Meeting soon",
        "body": f"{t} — in ~{minutes_until} min",
        "tag": f"meeting_soon_{meeting_id}",
        "data": {
            "type": "meeting_soon",
            "meeting_id": int(meeting_id),
            "minutes_until": int(minutes_until),
            "scheduled_at": scheduled_at_iso,
            "url": _command_center_shell("today"),
        },
    }


def notify_meeting_soon_if_configured(
    *,
    user_id: int,
    meeting_id: int,
    title: str,
    minutes_until: int,
    scheduled_at_iso: str,
) -> None:
    if not vapid_configured():
        return
    payload = _payload_meeting_soon(
        meeting_id=meeting_id,
        title=title,
        minutes_until=minutes_until,
        scheduled_at_iso=scheduled_at_iso,
    )
    send_payload_to_user(user_id=user_id, payload=payload, ttl=3600)


def _dedupe_once(key: str, ttl_sec: int) -> bool:
    """True if this key is fresh (should send). False if deduped."""
    try:
        from services.worker_heartbeat import redis_client

        r = redis_client()
        if r is not None:
            return bool(r.set(name=key, value="1", nx=True, ex=int(ttl_sec)))
    except Exception as exc:
        _log.debug("web_push redis dedupe: %s", exc)
    now = time.monotonic()
    exp = _memory_dedupe_expiry.get(key)
    if exp is not None and exp > now:
        return False
    _memory_dedupe_expiry[key] = now + float(ttl_sec)
    if len(_memory_dedupe_expiry) > 4000:
        dead = [k for k, v in _memory_dedupe_expiry.items() if v <= now]
        for k in dead[:2500]:
            _memory_dedupe_expiry.pop(k, None)
    return True


def run_emi_web_push_scan() -> dict[str, Any]:
    if not vapid_configured():
        return {"ok": True, "skipped": True}
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no_db"}
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=3)
    total = 0
    with factory() as session:
        rows = session.execute(
            select(PersonalLoan).where(
                PersonalLoan.is_closed.is_(False),
                PersonalLoan.next_due_date.isnot(None),
                PersonalLoan.next_due_date >= today,
                PersonalLoan.next_due_date <= horizon,
            )
        ).scalars().all()
        for loan in rows:
            uid = int(loan.user_id)
            lid = int(loan.id)
            due = loan.next_due_date
            if due is None:
                continue
            dedupe_key = f"thiramai:webpush:emi:{lid}:{due.isoformat()}"
            if not _redis_set_nx(dedupe_key, 86400 * 5):
                continue
            days = (due - today).days
            name = (loan.display_name or "Loan").strip()[:80]
            body = f"{name} — due in {days} day(s)" if days > 0 else f"{name} — due today"
            payload = {
                "title": "EMI reminder",
                "body": body,
                "tag": f"emi_due_{lid}_{due.isoformat()}",
                "data": {
                    "type": "emi_due",
                    "loan_id": lid,
                    "due": due.isoformat(),
                    "url": _command_center_shell("personal/finance"),
                },
            }
            out = send_payload_to_user(user_id=uid, payload=payload, ttl=86400)
            total += int(out.get("sent") or 0)
    return {"ok": True, "emi_notifications_sent": total}


def run_daily_brief_web_push_scan() -> dict[str, Any]:
    if not vapid_configured():
        return {"ok": True, "skipped": True}
    try:
        hour_utc = int((os.getenv("THIRAMAI_PUSH_DAILY_BRIEF_HOUR_UTC") or "2").strip())
    except ValueError:
        hour_utc = 2
    hour_utc = max(0, min(23, hour_utc))
    now = datetime.now(timezone.utc)
    if now.hour != hour_utc or now.minute > 14:
        return {"ok": True, "skipped": True, "reason": "outside_window"}
    today_s = now.date().isoformat()
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no_db"}
    total = 0
    with factory() as session:
        user_ids = list(session.scalars(select(PushSubscription.user_id).distinct()).all())
        for uid in user_ids:
            uid = int(uid)
            if uid <= 0:
                continue
            dedupe_key = f"thiramai:webpush:daily:{uid}:{today_s}"
            if not _dedupe_once(dedupe_key, 90000):
                continue
            u = session.get(User, uid)
            greet = "there"
            if u is not None:
                un = (getattr(u, "username", None) or "").strip()
                if un:
                    greet = un.replace("_", " ").split()[0]
                    greet = greet[:1].upper() + greet[1:] if greet else "there"
                else:
                    greet = (u.email or "").split("@", 1)[0].strip() or "there"
            payload = {
                "title": "Good morning",
                "body": f"{greet}, your THIRAMAI day is ready.",
                "tag": f"daily_brief_{uid}_{today_s}",
                "data": {
                    "type": "daily_brief",
                    "url": _command_center_shell("today"),
                },
            }
            out = send_payload_to_user(user_id=uid, payload=payload, ttl=43200)
            total += int(out.get("sent") or 0)
    return {"ok": True, "daily_brief_sent": total}


def register_web_push_jobs(scheduler: object) -> None:
    """Attach EMI + daily brief jobs to APScheduler."""
    from apscheduler.triggers.interval import IntervalTrigger

    if not vapid_configured():
        _log.info("web_push: VAPID not configured; scheduler jobs not registered")
        return

    def _emi_job():
        try:
            from core.observability import log_event, new_request_id

            out = run_emi_web_push_scan()
            log_event(new_request_id(), "web_push.emi_scan", ok=True, extra=out)
        except Exception:
            _log.exception("web_push emi scan failed")

    def _daily_job():
        try:
            from core.observability import log_event, new_request_id

            out = run_daily_brief_web_push_scan()
            if not out.get("skipped"):
                log_event(new_request_id(), "web_push.daily_scan", ok=True, extra=out)
        except Exception:
            _log.exception("web_push daily scan failed")

    scheduler.add_job(
        _emi_job,
        IntervalTrigger(minutes=30),
        id="thiramai_webpush_emi",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _daily_job,
        IntervalTrigger(minutes=5),
        id="thiramai_webpush_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _log.info("web_push: registered EMI (30m) + daily brief (5m) jobs")
