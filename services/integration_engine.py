"""Real-world integration engine for email, WhatsApp, and SMS."""

from __future__ import annotations

import json
import smtplib
import ssl
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import Integration, IntegrationMessageLog

# Core comms + domain "connector slots" (config_json holds provider-specific keys; send may no-op until implemented)
SUPPORTED_TYPES = {"email", "whatsapp", "sms", "marketplace", "suppliers", "messaging"}


def _session_factory_or_none():
    try:
        return get_session_factory()
    except Exception:
        return None


def _log_outgoing(
    *,
    user_id: int,
    integration_id: int | None,
    channel: str,
    recipient: str,
    subject: str | None,
    body: str,
    status: str,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    factory = _session_factory_or_none()
    if factory is None:
        return
    with factory() as session:
        session.add(
            IntegrationMessageLog(
                user_id=int(user_id),
                integration_id=int(integration_id) if integration_id else None,
                channel=str(channel or ""),
                recipient=str(recipient or ""),
                subject=str(subject) if subject else None,
                body=str(body or ""),
                status=str(status or "failed"),
                error_message=str(error_message) if error_message else None,
                metadata_json=metadata or {},
            )
        )
        session.commit()


def _get_integration(user_id: int, integration_type: str) -> Integration | None:
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        return session.execute(
            select(Integration)
            .where(
                Integration.user_id == int(user_id),
                Integration.type == str(integration_type or "").strip().lower(),
                Integration.enabled.is_(True),
            )
            .order_by(Integration.id.desc())
        ).scalars().first()


def list_integrations(user_id: int) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    with factory() as session:
        rows = (
            session.execute(
                select(Integration).where(Integration.user_id == int(user_id)).order_by(Integration.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": int(r.id),
                "type": str(r.type or ""),
                "config_json": r.config_json or {},
                "enabled": bool(r.enabled),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def list_outgoing_message_logs(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    factory = _session_factory_or_none()
    if factory is None:
        return []
    lim = max(1, min(int(limit), 300))
    with factory() as session:
        rows = (
            session.execute(
                select(IntegrationMessageLog)
                .where(IntegrationMessageLog.user_id == int(user_id))
                .order_by(IntegrationMessageLog.created_at.desc(), IntegrationMessageLog.id.desc())
                .limit(lim)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": int(r.id),
                "integration_id": int(r.integration_id) if r.integration_id else None,
                "channel": str(r.channel or ""),
                "recipient": str(r.recipient or ""),
                "subject": str(r.subject or "") if r.subject else None,
                "status": str(r.status or ""),
                "error_message": str(r.error_message or "") if r.error_message else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def upsert_integration(*, user_id: int, integration_type: str, config_json: dict[str, Any], enabled: bool) -> dict[str, Any] | None:
    itype = str(integration_type or "").strip().lower()
    if itype not in SUPPORTED_TYPES:
        return None
    factory = _session_factory_or_none()
    if factory is None:
        return None
    with factory() as session:
        row = (
            session.execute(
                select(Integration).where(Integration.user_id == int(user_id), Integration.type == itype).order_by(Integration.id.desc())
            )
            .scalars()
            .first()
        )
        if row is None:
            row = Integration(user_id=int(user_id), type=itype)
            session.add(row)
        row.config_json = config_json or {}
        row.enabled = bool(enabled)
        session.commit()
        return {"id": int(row.id)}


def _send_email_with_retry(config: dict[str, Any], to: str, subject: str, body: str, retries: int = 3) -> dict[str, Any]:
    host = str(config.get("smtp_host") or "").strip()
    port = int(config.get("smtp_port") or 587)
    username = str(config.get("smtp_username") or "").strip()
    password = str(config.get("smtp_password") or "").strip()
    from_email = str(config.get("from_email") or username).strip()
    use_ssl = bool(config.get("smtp_ssl"))
    use_tls = bool(config.get("smtp_tls", True))
    if not host or not username or not password or not from_email:
        return {"ok": False, "error": "Missing SMTP configuration"}

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    last_error = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) as server:
                    server.login(username, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    if use_tls:
                        server.starttls(context=ssl.create_default_context())
                    server.login(username, password)
                    server.send_message(msg)
            return {"ok": True, "attempts": attempt}
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
            if attempt < retries:
                time.sleep(min(2 * attempt, 5))
    return {"ok": False, "error": last_error or "SMTP send failed", "attempts": retries}


def _http_post_json(url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[bool, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            payload = resp.read().decode("utf-8", errors="replace")
            return (200 <= status < 300), payload[:3000]
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def send_email(user_id: int, to: str, subject: str, body: str) -> dict[str, Any]:
    integ = _get_integration(user_id, "email")
    if integ is None:
        out = {"ok": False, "error": "Email integration not configured or disabled"}
        _log_outgoing(user_id=user_id, integration_id=None, channel="email", recipient=to, subject=subject, body=body, status="failed", error_message=out["error"])
        return out
    out = _send_email_with_retry(integ.config_json or {}, to, subject, body, retries=3)
    _log_outgoing(
        user_id=user_id,
        integration_id=int(integ.id),
        channel="email",
        recipient=to,
        subject=subject,
        body=body,
        status="success" if out.get("ok") else "failed",
        error_message=out.get("error"),
        metadata={"attempts": out.get("attempts")},
    )
    return out


def send_whatsapp(user_id: int, number: str, message: str) -> dict[str, Any]:
    integ = _get_integration(user_id, "whatsapp")
    if integ is None:
        out = {"ok": False, "error": "WhatsApp integration not configured or disabled"}
        _log_outgoing(user_id=user_id, integration_id=None, channel="whatsapp", recipient=number, subject=None, body=message, status="failed", error_message=out["error"])
        return out
    cfg = integ.config_json or {}
    provider = str(cfg.get("provider") or "twilio").strip().lower()
    if provider == "twilio":
        sid = str(cfg.get("account_sid") or "").strip()
        token = str(cfg.get("auth_token") or "").strip()
        from_number = str(cfg.get("from_number") or "").strip()
        if not sid or not token or not from_number:
            out = {"ok": False, "error": "Missing Twilio WhatsApp config"}
        else:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Messages.json"
            payload = {
                "To": f"whatsapp:{number}",
                "From": f"whatsapp:{from_number}",
                "Body": message,
            }
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Authorization", "Basic " + _basic_auth_token(sid, token))
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    ok = 200 <= int(getattr(resp, "status", 200) or 200) < 300
                    body_text = resp.read().decode("utf-8", errors="replace")[:3000]
                    out = {"ok": ok, "provider": "twilio", "response": body_text}
            except Exception as exc:  # pragma: no cover
                out = {"ok": False, "error": str(exc), "provider": "twilio"}
    else:
        url = str(cfg.get("api_url") or "").strip()
        token = str(cfg.get("api_token") or "").strip()
        if not url:
            out = {"ok": False, "error": "Missing WhatsApp API url"}
        else:
            ok, payload = _http_post_json(
                url,
                {"to": number, "message": message},
                {"Authorization": f"Bearer {token}"} if token else {},
            )
            out = {"ok": ok, "provider": provider, "response": payload if ok else None, "error": None if ok else payload}
    _log_outgoing(
        user_id=user_id,
        integration_id=int(integ.id),
        channel="whatsapp",
        recipient=number,
        subject=None,
        body=message,
        status="success" if out.get("ok") else "failed",
        error_message=out.get("error"),
        metadata={"provider": out.get("provider")},
    )
    return out


def send_sms(user_id: int, number: str, message: str) -> dict[str, Any]:
    integ = _get_integration(user_id, "sms")
    if integ is None:
        out = {"ok": False, "error": "SMS integration not configured or disabled"}
        _log_outgoing(user_id=user_id, integration_id=None, channel="sms", recipient=number, subject=None, body=message, status="failed", error_message=out["error"])
        return out
    cfg = integ.config_json or {}
    api_url = str(cfg.get("api_url") or "").strip()
    api_token = str(cfg.get("api_token") or "").strip()
    from_number = str(cfg.get("from_number") or "").strip()
    if not api_url:
        out = {"ok": False, "error": "Missing SMS provider api_url"}
    else:
        ok, payload = _http_post_json(
            api_url,
            {"to": number, "from": from_number, "message": message},
            {"Authorization": f"Bearer {api_token}"} if api_token else {},
        )
        out = {"ok": ok, "response": payload if ok else None, "error": None if ok else payload}
    _log_outgoing(
        user_id=user_id,
        integration_id=int(integ.id),
        channel="sms",
        recipient=number,
        subject=None,
        body=message,
        status="success" if out.get("ok") else "failed",
        error_message=out.get("error"),
        metadata={},
    )
    return out


def notify_user(user_id: int, message: str, subject: str = "Thiramai Notification") -> dict[str, Any]:
    email_integration = _get_integration(user_id, "email")
    whatsapp_integration = _get_integration(user_id, "whatsapp")
    if email_integration is not None:
        to_email = str((email_integration.config_json or {}).get("default_to") or "").strip()
        if to_email:
            return send_email(user_id, to_email, subject, message)
    if whatsapp_integration is not None:
        to_num = str((whatsapp_integration.config_json or {}).get("default_to") or "").strip()
        if to_num:
            return send_whatsapp(user_id, to_num, message)
    out = {"ok": False, "error": "No enabled integration with default recipient"}
    _log_outgoing(
        user_id=user_id,
        integration_id=None,
        channel="notify_user",
        recipient="",
        subject=subject,
        body=message,
        status="failed",
        error_message=out["error"],
    )
    return out


def _basic_auth_token(username: str, password: str) -> str:
    import base64

    raw = f"{username}:{password}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def test_integration(user_id: int, integration_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    p = payload or {}
    itype = str(integration_type or "").strip().lower()
    if itype == "email":
        return send_email(user_id, str(p.get("to") or ""), str(p.get("subject") or "Thiramai Test"), str(p.get("body") or "Test email"))
    if itype == "whatsapp":
        return send_whatsapp(user_id, str(p.get("number") or ""), str(p.get("message") or "Test WhatsApp message"))
    if itype == "sms":
        return send_sms(user_id, str(p.get("number") or ""), str(p.get("message") or "Test SMS message"))
    if itype in ("marketplace", "suppliers", "messaging"):
        integ = _get_integration(user_id, itype)
        if integ is None:
            return {"ok": False, "error": f"{itype} integration not configured or disabled"}
        cfg = integ.config_json or {}
        if itype == "messaging" and (cfg.get("webhook_url") or cfg.get("url")):
            return {"ok": True, "mode": "config_valid", "provider": str(cfg.get("provider") or "webhook")}
        if itype in ("marketplace", "suppliers") and (cfg.get("api_key") or cfg.get("base_url") or cfg.get("search_endpoint")):
            return {"ok": True, "mode": "config_valid", "provider": str(cfg.get("provider") or "custom")}
        return {"ok": True, "mode": "stub", "message": f"{itype} slot stored; add api_key / base_url to enable live tests."}
    return {"ok": False, "error": "Unsupported integration type"}
