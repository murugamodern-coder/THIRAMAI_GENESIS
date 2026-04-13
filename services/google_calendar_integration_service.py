"""
Google Calendar OAuth + push Thiramai meetings to ``primary`` calendar.

Requires env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
and pip: google-auth google-auth-oauthlib google-api-python-client google-auth-httplib2
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt
from jose.exceptions import JWTError
from sqlalchemy import select
from core.database import get_session_factory
from core.db.models import PersonalMeeting, UserIntegration
from services import integration_crypto as ic
from services.personal_meetings_service import ACTIVE_STATUSES

_log = logging.getLogger("thiramai.google_calendar")

GCAL_TYPE = "google_calendar"
_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _secret() -> str:
    return (
        os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET") or ""
    ).strip()


def _redirect_uri() -> str:
    return (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()


def _client_id() -> str:
    return (os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()


def oauth_configured() -> bool:
    return bool(_client_id() and _client_secret() and _redirect_uri())


def encode_oauth_state(*, user_id: int) -> str:
    if not _secret():
        raise RuntimeError("SECRET_KEY required for OAuth state")
    exp = datetime.now(timezone.utc) + timedelta(minutes=15)
    return jwt.encode(
        {"sub": str(int(user_id)), "purpose": "gcal_oauth", "exp": exp},
        _secret(),
        algorithm="HS256",
    )


def decode_oauth_state(state: str) -> int:
    claims = jwt.decode(state, _secret(), algorithms=["HS256"], options={"verify_aud": False})
    if claims.get("purpose") != "gcal_oauth":
        raise JWTError("invalid purpose")
    return int(str(claims.get("sub") or "0"))


def build_authorization_url(*, user_id: int) -> str:
    from google_auth_oauthlib.flow import Flow

    if not oauth_configured():
        raise RuntimeError("Google OAuth env not configured (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI)")
    st = encode_oauth_state(user_id=int(user_id))
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [_redirect_uri()],
            }
        },
        scopes=_SCOPES,
    )
    flow.redirect_uri = _redirect_uri()
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=st,
    )
    return url


def _flow_for_callback() -> Any:
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        {
            "web": {
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [_redirect_uri()],
            }
        },
        scopes=_SCOPES,
        redirect_uri=_redirect_uri(),
    )


def handle_oauth_callback(*, code: str, state: str) -> tuple[bool, str, int | None]:
    uid: int | None = None
    try:
        uid = decode_oauth_state(state)
    except Exception as e:
        return False, f"invalid state: {e}", None
    if uid <= 0:
        return False, "invalid user in state", None
    try:
        flow = _flow_for_callback()
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as e:
        _log.exception("google token exchange failed")
        return False, str(e) or "token exchange failed", uid

    access = creds.token or ""
    refresh = creds.refresh_token or ""
    exp = None
    if creds.expiry:
        exp = creds.expiry
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

    factory = get_session_factory()
    if factory is None:
        return False, "database not configured", uid
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == uid,
                    UserIntegration.integration_type == GCAL_TYPE,
                )
            ).scalar_one_or_none()
            if row is None:
                row = UserIntegration(
                    user_id=uid,
                    integration_type=GCAL_TYPE,
                    is_active=True,
                    scope=",".join(_SCOPES),
                    meta_json={},
                )
                session.add(row)
            row.access_token_enc = ic.encrypt_secret(access)
            row.refresh_token_enc = ic.encrypt_secret(refresh) if refresh else row.refresh_token_enc
            row.expires_at = exp
            row.is_active = True
            row.scope = ",".join(_SCOPES)
    return True, "ok", uid


def _credentials_from_row(row: UserIntegration) -> Any | None:
    from google.oauth2.credentials import Credentials

    access = ic.decrypt_secret(row.access_token_enc)
    refresh = ic.decrypt_secret(row.refresh_token_enc)
    if not access and not refresh:
        return None
    return Credentials(
        token=access,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_client_id(),
        client_secret=_client_secret(),
        scopes=_SCOPES,
    )


def get_calendar_credentials(*, user_id: int) -> Any | None:
    factory = get_session_factory()
    if factory is None:
        return None
    row_id: int | None = None
    creds = None
    with factory() as session:
        row = session.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == int(user_id),
                UserIntegration.integration_type == GCAL_TYPE,
                UserIntegration.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row_id = int(row.id)
        creds = _credentials_from_row(row)
    if creds is None:
        return None
    if getattr(creds, "expired", False) and creds.refresh_token:
        try:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            with factory() as session:
                with session.begin():
                    r2 = session.get(UserIntegration, row_id)
                    if r2 is not None:
                        r2.access_token_enc = ic.encrypt_secret(creds.token or "")
                        if creds.refresh_token:
                            r2.refresh_token_enc = ic.encrypt_secret(creds.refresh_token)
                        r2.expires_at = creds.expiry
        except Exception:
            _log.exception("refresh google token failed")
            return None
    return creds


def _event_body(m: PersonalMeeting) -> dict[str, Any]:
    start = m.scheduled_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=max(1, int(m.duration_minutes or 60)))
    return {
        "summary": (m.title or "Meeting")[:2000],
        "description": ((m.agenda or "")[:8000]),
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }


def delete_calendar_event(*, user_id: int, event_id: str) -> bool:
    """Remove an event from the user's primary calendar. Returns True if deleted or already gone."""
    eid = (event_id or "").strip()
    if not eid:
        return True
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        _log.warning("google-api-python-client not installed")
        return False
    creds = get_calendar_credentials(user_id=user_id)
    if creds is None:
        return False
    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        service.events().delete(calendarId="primary", eventId=eid).execute()
        return True
    except HttpError as e:
        code = getattr(e, "status_code", None) or getattr(getattr(e, "resp", None), "status", None)
        if code == 404:
            return True
        _log.warning("google calendar delete failed: %s", e)
        return False
    except Exception:
        _log.exception("google calendar delete failed")
        return False


def push_meeting_event(*, user_id: int, meeting: PersonalMeeting) -> str | None:
    try:
        from googleapiclient.discovery import build
    except ImportError:
        _log.warning("google-api-python-client not installed")
        return None
    creds = get_calendar_credentials(user_id=user_id)
    if creds is None:
        return None
    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        body = _event_body(meeting)
        if meeting.google_event_id:
            ev = (
                service.events()
                .update(calendarId="primary", eventId=meeting.google_event_id, body=body)
                .execute()
            )
            return str(ev.get("id") or meeting.google_event_id)
        ev = service.events().insert(calendarId="primary", body=body).execute()
        return str(ev.get("id") or "")
    except Exception:
        _log.exception("google calendar insert/update failed")
        return None


def try_push_new_meeting(*, user_id: int, organization_id: int, meeting_id: int) -> None:
    if not oauth_configured():
        return
    factory = get_session_factory()
    if factory is None or int(user_id) <= 0:
        return
    try:
        with factory() as session:
            m = session.execute(
                select(PersonalMeeting).where(
                    PersonalMeeting.id == int(meeting_id),
                    PersonalMeeting.user_id == int(user_id),
                    PersonalMeeting.organization_id == int(organization_id),
                )
            ).scalar_one_or_none()
            if m is None or m.status not in ACTIVE_STATUSES:
                return
            mid = int(m.id)
        eid = push_meeting_event(user_id=user_id, meeting=m)
        if eid:
            with factory() as session:
                with session.begin():
                    m2 = session.get(PersonalMeeting, mid)
                    if m2 is not None:
                        m2.google_event_id = eid[:256]
    except Exception:
        _log.exception("try_push_new_meeting failed")


def sync_all_meetings_for_user(*, user_id: int) -> dict[str, Any]:
    uid = int(user_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no database"}
    pushed = 0
    errors = 0
    with factory() as session:
        rows = list(
            session.execute(
                select(PersonalMeeting).where(
                    PersonalMeeting.user_id == uid,
                    PersonalMeeting.status.in_(tuple(ACTIVE_STATUSES)),
                )
            ).scalars().all()
        )
    for m in rows:
        try:
            eid = push_meeting_event(user_id=uid, meeting=m)
            if eid:
                with factory() as session:
                    with session.begin():
                        mx = session.get(PersonalMeeting, m.id)
                        if mx is not None:
                            mx.google_event_id = eid[:256]
                pushed += 1
            else:
                errors += 1
        except Exception:
            errors += 1
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == uid,
                    UserIntegration.integration_type == GCAL_TYPE,
                )
            ).scalar_one_or_none()
            if row is not None:
                row.last_synced_at = datetime.now(timezone.utc)
    return {"ok": True, "pushed": pushed, "errors": errors, "total": len(rows)}


def disconnect_user(*, user_id: int) -> dict[str, Any]:
    """Clear stored tokens and mark integration inactive."""
    uid = int(user_id)
    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "no database"}
    with factory() as session:
        with session.begin():
            row = session.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == uid,
                    UserIntegration.integration_type == GCAL_TYPE,
                )
            ).scalar_one_or_none()
            if row is None:
                return {"ok": True, "disconnected": False}
            row.access_token_enc = None
            row.refresh_token_enc = None
            row.expires_at = None
            row.is_active = False
            row.last_synced_at = None
    return {"ok": True, "disconnected": True}


def integration_status(*, user_id: int) -> dict[str, Any]:
    uid = int(user_id)
    factory = get_session_factory()
    if factory is None:
        return {"connected": False, "oauth_configured": oauth_configured()}
    with factory() as session:
        row = session.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == uid,
                UserIntegration.integration_type == GCAL_TYPE,
            )
        ).scalar_one_or_none()
        if row is None or not row.is_active:
            return {
                "connected": False,
                "oauth_configured": oauth_configured(),
                "last_synced_at": None,
            }
        return {
            "connected": bool(row.access_token_enc or row.refresh_token_enc),
            "oauth_configured": oauth_configured(),
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }
