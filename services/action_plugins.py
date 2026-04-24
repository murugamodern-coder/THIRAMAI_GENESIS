"""Built-in action plugins: email, file, HTTP API, in-app notification."""

from __future__ import annotations

import os
import smtplib
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx

from core.database import get_session_factory
from core.db.models import Notification


def _session_factory():
    return get_session_factory()


def _vault_actions_root() -> Path:
    root = Path(__file__).resolve().parent.parent / "vault" / "actions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def plugin_send_email(payload: dict[str, Any]) -> dict[str, Any]:
    to_addr = str(payload.get("to") or "").strip()
    subject = str(payload.get("subject") or "Thiramai notification").strip()[:400]
    body = str(payload.get("body") or "").strip()
    host = (os.getenv("THIRAMAI_SMTP_HOST") or "").strip()
    port = int((os.getenv("THIRAMAI_SMTP_PORT") or "587").strip() or "587")
    user = (os.getenv("THIRAMAI_SMTP_USER") or "").strip()
    password = (os.getenv("THIRAMAI_SMTP_PASSWORD") or "").strip()
    from_addr = (os.getenv("THIRAMAI_SMTP_FROM") or user or "noreply@localhost").strip()

    if not to_addr:
        return {"ok": False, "error": "recipient `to` is required for plugin_email"}
    if not host:
        return {
            "ok": False,
            "simulated": True,
            "error": "THIRAMAI_SMTP_HOST not configured; email not sent",
            "would_send": {"from": from_addr, "to": to_addr, "subject": subject},
        }

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body or "(empty)")

    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True, "to": to_addr, "subject": subject}
    except Exception as exc:  # pragma: no cover
        le = str(exc).lower()
        ec = "network" if any(x in le for x in ("refused", "timeout", "gaierror", "connect", "ssl")) else "api"
        return {"ok": False, "error": str(exc), "error_class": ec}


def plugin_create_file(payload: dict[str, Any]) -> dict[str, Any]:
    rel = str(payload.get("path") or f"actions/out_{uuid.uuid4().hex[:10]}.txt").strip().replace("..", "_")
    content = str(payload.get("content") or "")
    root = _vault_actions_root()
    candidate = (root / rel.lstrip("/\\")).resolve()
    try:
        candidate.relative_to(root)
        path = candidate
    except ValueError:
        path = (root / Path(rel).name).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(path), "bytes": len(content.encode("utf-8"))}


def plugin_http_api(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    method = str(payload.get("method") or "GET").upper()
    if not url:
        return {"ok": False, "error": "url required for plugin_api"}
    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    j = payload.get("json")
    timeout = float(payload.get("timeout_seconds") or 30.0)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.request(method, url, headers=headers, json=j)
        out: dict[str, Any] = {
            "ok": 200 <= resp.status_code < 400,
            "status_code": resp.status_code,
            "url": url,
        }
        ct = (resp.headers.get("content-type") or "").lower()
        if "json" in ct:
            try:
                out["json"] = resp.json()
            except Exception:
                out["text_preview"] = (resp.text or "")[:2000]
        else:
            out["text_preview"] = (resp.text or "")[:2000]
        return out
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url, "method": method}


def plugin_notification(*, organization_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "Action").strip()[:300]
    body = str(payload.get("body") or "").strip()[:4000]
    severity = str(payload.get("severity") or "info").strip()[:16]
    factory = _session_factory()
    if factory is None:
        return {"ok": True, "simulated": True, "message": "DATABASE_URL not set; notification not persisted"}
    dedupe = f"action_layer:{uuid.uuid4().hex[:20]}"
    with factory() as session:
        row = Notification(
            organization_id=int(organization_id),
            kind="action_execution",
            severity=severity,
            title=title,
            body=body,
            reference_type="action_plugin",
            reference_id=None,
            payload={"source": "action_plugins.plugin_notification"},
            dedupe_key=dedupe[:250],
        )
        session.add(row)
        session.commit()
        return {"ok": True, "notification_id": int(row.id)}


def run_plugin(
    name: str,
    payload: dict[str, Any],
    *,
    organization_id: int,
) -> dict[str, Any]:
    n = (name or "").strip().lower()
    if n in {"email", "plugin_email", "send_email"}:
        return plugin_send_email(payload)
    if n in {"file", "plugin_file", "create_file"}:
        return plugin_create_file(payload)
    if n in {"api", "plugin_api", "http"}:
        return plugin_http_api(payload)
    if n in {"notify", "plugin_notify", "notification"}:
        return plugin_notification(organization_id=int(organization_id), payload=payload)
    return {"ok": False, "error": f"unknown plugin: {name}"}
