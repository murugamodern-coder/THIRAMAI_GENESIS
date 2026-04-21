"""
Unified safe connector surface for autonomous agents.

All mutating paths are guarded; dangerous operations are rejected.
Every invocation is appended to the SQLite connector audit table when persistence is enabled.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _connector_audit(at: str, result: dict[str, Any]) -> None:
    try:
        from thiramai.runtime.sqlite_job_store import append_connector_audit

        append_connector_audit(
            at,
            bool(result.get("ok")),
            {
                "error": (result.get("error") or "")[:500],
                "keys": list(result.keys())[:16],
            },
        )
    except Exception:
        pass


def _max_file_cap() -> int:
    try:
        from thiramai.config import THIRAMAI_CONNECTOR_MAX_FILE_BYTES

        return max(1024, int(THIRAMAI_CONNECTOR_MAX_FILE_BYTES))
    except Exception:
        return 2_000_000


def execute_action(action_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Dispatch a safe action. *action_type* is lower-case.

    Supported:
    - ``system.read_file`` — read text file under repo (max size cap)
    - ``system.write_file`` — write text file under repo (disabled unless THIRAMAI_CONNECTOR_WRITE=1)
    - ``system.shell_meta`` — return allowlist summary (no execution)
    - ``http.get`` — GET URL with timeout (allowlist hosts optional)
    - ``api.internal_health`` — GET /health/live and /health/ready on localhost
    - ``db.ping`` — requires DB; uses existing engine if available
    """
    p = payload if isinstance(payload, dict) else {}
    at = (action_type or "").strip().lower()
    out: dict[str, Any]

    if at == "system.read_file":
        rel = str(p.get("path", "")).strip().replace("\\", "/")
        if ".." in rel or rel.startswith("/"):
            out = {"ok": False, "error": "path must be relative and stay within repo"}
            _connector_audit(at, out)
            return out
        path = (ROOT / rel).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            out = {"ok": False, "error": "path outside repo root"}
            _connector_audit(at, out)
            return out
        cap = _max_file_cap()
        max_bytes = min(int(p.get("max_bytes", 256_000) or 256_000), cap)
        try:
            data = path.read_bytes()[:max_bytes]
            text = data.decode("utf-8", errors="replace")
            out = {"ok": True, "path": str(path.relative_to(ROOT)), "content": text, "truncated": len(data) >= max_bytes}
        except OSError as e:
            out = {"ok": False, "error": str(e)}
        _connector_audit(at, out)
        return out

    if at == "system.write_file":
        if not _truthy("THIRAMAI_CONNECTOR_WRITE"):
            out = {"ok": False, "error": "writes disabled (set THIRAMAI_CONNECTOR_WRITE=1)"}
            _connector_audit(at, out)
            return out
        rel = str(p.get("path", "")).strip().replace("\\", "/")
        if ".." in rel:
            out = {"ok": False, "error": "invalid path"}
            _connector_audit(at, out)
            return out
        try:
            from connectors.protection import is_write_protected
        except ImportError:
            is_write_protected = lambda _p: False  # noqa: E731
        if is_write_protected(rel):
            out = {"ok": False, "error": "write blocked: protected path (self-improvement lock)"}
            _connector_audit(at, out)
            return out
        path = (ROOT / rel).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError:
            out = {"ok": False, "error": "path outside repo root"}
            _connector_audit(at, out)
            return out
        content = str(p.get("content", ""))
        if len(content.encode("utf-8")) > _max_file_cap():
            out = {"ok": False, "error": f"content exceeds max bytes ({_max_file_cap()})"}
            _connector_audit(at, out)
            return out
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            out = {"ok": True, "path": str(path.relative_to(ROOT)), "bytes": len(content.encode("utf-8"))}
        except OSError as e:
            out = {"ok": False, "error": str(e)}
        _connector_audit(at, out)
        return out

    if at == "system.shell_meta":
        try:
            from thiramai.config import ALLOWED_COMMANDS  # type: ignore[import-not-found]

            out = {"ok": True, "allowed_commands": sorted(str(x) for x in ALLOWED_COMMANDS)}
        except Exception as e:
            out = {"ok": False, "error": str(e)}
        _connector_audit(at, out)
        return out

    if at == "http.get":
        from urllib.parse import urlparse

        url = str(p.get("url", "")).strip()
        if not url.startswith("https://") and not url.startswith("http://"):
            out = {"ok": False, "error": "only http(s) URLs"}
            _connector_audit(at, out)
            return out
        pu = urlparse(url)
        host = (pu.hostname or "").lower()
        local_host = host in {"", "localhost", "127.0.0.1", "::1"}
        allowed = (os.getenv("THIRAMAI_CONNECTOR_HTTP_HOSTS") or "").strip()
        try:
            from thiramai.config import effective_connector_http_strict

            strict = effective_connector_http_strict()
        except Exception:
            strict = _truthy("THIRAMAI_CONNECTOR_HTTP_STRICT")
        if strict and not allowed and not local_host:
            out = {
                "ok": False,
                "error": "THIRAMAI_CONNECTOR_HTTP_STRICT requires THIRAMAI_CONNECTOR_HTTP_HOSTS for non-loopback URLs",
            }
            _connector_audit(at, out)
            return out
        if allowed:
            ok_host = any(
                host == h.strip().lower() or host.endswith("." + h.strip().lower())
                for h in allowed.split(",")
                if h.strip()
            )
            if not ok_host:
                out = {"ok": False, "error": f"host not in allow-list: {allowed}"}
                _connector_audit(at, out)
                return out
        base = f"{pu.scheme}://{pu.netloc}"
        cb = None
        try:
            from core.stability.circuit_breaker import circuit_key_for_url, get_circuit_breaker

            cb = get_circuit_breaker("conn_http_" + circuit_key_for_url(base))
            if not cb.allow_request():
                out = {"ok": False, "error": "circuit_open", "detail": base}
                _connector_audit(at, out)
                return out
        except ImportError:
            cb = None
        timeout = min(float(p.get("timeout_sec", 15) or 15), 120.0)
        try:
            req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(500_000).decode("utf-8", errors="replace")
                if cb:
                    cb.record_success()
                out = {"ok": True, "status": resp.status, "body_preview": body[:8000]}
        except urllib.error.HTTPError as e:
            if cb:
                cb.record_failure()
            out = {"ok": False, "error": f"HTTP {e.code}", "detail": e.read(4000).decode("utf-8", errors="replace")}
        except Exception as e:
            if cb:
                cb.record_failure()
            out = {"ok": False, "error": str(e)}
        _connector_audit(at, out)
        return out

    if at == "api.internal_health":
        port = (os.getenv("THIRAMAI_PORT") or "8000").strip() or "8000"
        base = f"http://127.0.0.1:{port}"
        out_d: dict[str, Any] = {"ok": True, "base": base}
        for hpath in ("/health/live", "/health/ready"):
            try:
                req = urllib.request.Request(f"{base}{hpath}", method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    out_d[hpath] = {"status": resp.status, "body": resp.read(4096).decode("utf-8", errors="replace")[:2000]}
            except Exception as e:
                out_d[hpath] = {"error": str(e)}
        _connector_audit(at, out_d)
        return out_d

    if at == "db.ping":
        try:
            from core.database import get_engine  # noqa: WPS433

            eng = get_engine()
            if eng is None:
                out = {"ok": False, "error": "database not configured"}
                _connector_audit(at, out)
                return out
            from sqlalchemy import text

            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            out = {"ok": True, "detail": "select 1 ok"}
        except Exception as e:
            out = {"ok": False, "error": str(e)}
        _connector_audit(at, out)
        return out

    out = {"ok": False, "error": f"unknown action_type: {action_type}", "supported": [
        "system.read_file",
        "system.write_file",
        "system.shell_meta",
        "http.get",
        "api.internal_health",
        "db.ping",
    ]}
    _connector_audit(at, out)
    return out
