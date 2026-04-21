"""
User-scoped runtime configuration (allowed env-style keys).

Persistence: PostgreSQL ``user_runtime_config``; optional mirror to repo-root ``.env.local``
for local single-tenant workflows (THIRAMAI_MIRROR_CONFIG_TO_ENV_LOCAL=1).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from core.database import get_engine, get_session_factory, worker_session_scope

_log = logging.getLogger("thiramai.vault")

# Keys the API / agent may set (UPPER_SNAKE). Values are secrets or small flags.
ALLOWED_RUNTIME_KEYS: frozenset[str] = frozenset(
    {
        "FYERS_CLIENT_ID",
        "FYERS_SECRET_KEY",
        "FYERS_ACCESS_TOKEN",
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "KITE_ACCESS_TOKEN",
        "THIRAMAI_BROKER_PROVIDER",
        "THIRAMAI_TRADE_RISK_PERCENT",
        "THIRAMAI_TRADING_CAPITAL_INR",
        "THIRAMAI_SMART_SIZING_ENABLED",
        "THIRAMAI_SENTIMENT_OVERLAY_ENABLED",
        "THIRAMAI_SENTIMENT_RESUME_AT",
        "THIRAMAI_TRADING_HALT_ACTIVE",
        "THIRAMAI_TRADING_HALT_IST_DATE",
    }
)

# Encrypted at rest with Fernet (THIRAMAI_VAULT_FERNET_KEY / FERNET_KEY); never written to .env.local in production.
ENCRYPT_AT_REST_KEYS: frozenset[str] = frozenset(
    {
        "FYERS_CLIENT_ID",
        "FYERS_SECRET_KEY",
        "FYERS_ACCESS_TOKEN",
        "KITE_API_KEY",
        "KITE_API_SECRET",
        "KITE_ACCESS_TOKEN",
    }
)

_FERNET_ATTEMPTED = False
_FERNET: Any = None


def _production_environment() -> bool:
    return (os.getenv("ENV") or os.getenv("THIRAMAI_ENV") or "").strip().lower() == "production"


def _get_fernet():
    """Return Fernet instance or None if key missing (non-fatal for non-secret keys)."""
    global _FERNET_ATTEMPTED, _FERNET
    if _FERNET_ATTEMPTED:
        return _FERNET
    _FERNET_ATTEMPTED = True
    raw = (os.getenv("THIRAMAI_VAULT_FERNET_KEY") or os.getenv("FERNET_KEY") or "").strip()
    if not raw:
        _FERNET = None
        return None
    try:
        from cryptography.fernet import Fernet

        _FERNET = Fernet(raw.encode("utf-8"))
        return _FERNET
    except Exception as exc:
        _log.error("vault: invalid THIRAMAI_VAULT_FERNET_KEY / FERNET_KEY: %s", exc)
        _FERNET = None
        return None


def _encrypt_at_rest(key: str, plain: str) -> str:
    if key not in ENCRYPT_AT_REST_KEYS:
        return plain
    f = _get_fernet()
    if f is None:
        raise RuntimeError(
            "THIRAMAI_VAULT_FERNET_KEY (or FERNET_KEY) is required to store broker credentials. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    token = f.encrypt(plain.encode("utf-8")).decode("ascii")
    return f"v1:{token}"


def _decrypt_at_rest(key: str, stored: str) -> str:
    if key not in ENCRYPT_AT_REST_KEYS:
        return stored
    s = str(stored or "")
    if not s.startswith("v1:"):
        return s
    f = _get_fernet()
    if f is None:
        _log.warning("vault: ciphertext present for %s but no Fernet key — cannot decrypt", key)
        return ""
    try:
        return f.decrypt(s[3:].encode("ascii")).decode("utf-8")
    except Exception as exc:
        _log.warning("vault: decrypt failed for %s: %s", key, exc)
        return ""

_KEY_ALIASES: dict[str, str] = {
    "FYERS_SECRET": "FYERS_SECRET_KEY",
    "FYERS_API_KEY": "FYERS_CLIENT_ID",
}

_SENSITIVE_SUFFIXES: tuple[str, ...] = (
    "_TOKEN",
    "_SECRET",
    "_KEY",
    "PASSWORD",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_canonical_key(raw: str) -> str | None:
    k = str(raw or "").strip().upper().replace(" ", "_")
    if not k:
        return None
    k = _KEY_ALIASES.get(k, k)
    return k if k in ALLOWED_RUNTIME_KEYS else None


def mask_for_log(key: str, value: str | None) -> str:
    if value is None or value == "":
        return "(empty)"
    k = str(key).upper()
    if any(x in k for x in _SENSITIVE_SUFFIXES) or "SECRET" in k or "TOKEN" in k:
        if len(value) <= 6:
            return "***"
        return f"{value[:2]}***{value[-2:]}"
    return value[:120]


def _mirror_env_local_enabled() -> bool:
    if _production_environment():
        return False
    return (os.getenv("THIRAMAI_MIRROR_CONFIG_TO_ENV_LOCAL") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def merge_env_local_keys(updates: dict[str, str]) -> None:
    """Append/update KEY=value lines in ``.env.local`` at repo root (optional). Never mirrors secrets."""
    if not _mirror_env_local_enabled() or not updates:
        return
    updates = {k: v for k, v in updates.items() if k not in ENCRYPT_AT_REST_KEYS}
    if not updates:
        return
    path = _repo_root() / ".env.local"
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            key = m.group(1).upper()
            if key in updates:
                seen.add(key)
                out.append(f"{key}={updates[key]}")
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    try:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError as exc:
        _log.warning("env.local mirror failed: %s", exc)


def _load_all_for_user_sqlite_fallback(user_id: int, session) -> dict[str, str]:
    rows = session.execute(
        text("SELECT config_key, config_value FROM user_runtime_config WHERE user_id = :uid"),
        {"uid": int(user_id)},
    ).all()
    out: dict[str, str] = {}
    for r in rows:
        k = str(r[0])
        raw = str(r[1])
        out[k] = _decrypt_at_rest(k, raw)
    return out


def _upsert_pair(user_id: int, key: str, value: str) -> None:
    eng = get_engine()
    if eng is None:
        _log.warning("vault upsert skipped: no database engine")
        return
    dialect = eng.dialect.name
    uid = int(user_id)
    with worker_session_scope() as session:
        if dialect == "postgresql":
            session.execute(
                text(
                    """
                    INSERT INTO user_runtime_config (user_id, config_key, config_value, updated_at)
                    VALUES (:uid, :k, :v, now())
                    ON CONFLICT (user_id, config_key)
                    DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now()
                    """
                ),
                {"uid": uid, "k": key, "v": value},
            )
        else:
            session.execute(
                text("DELETE FROM user_runtime_config WHERE user_id = :uid AND config_key = :k"),
                {"uid": uid, "k": key},
            )
            session.execute(
                text(
                    """
                    INSERT INTO user_runtime_config (user_id, config_key, config_value, updated_at)
                    VALUES (:uid, :k, :v, CURRENT_TIMESTAMP)
                    """
                ),
                {"uid": uid, "k": key, "v": value},
            )


def load_user_config_map(user_id: int) -> dict[str, str]:
    factory = get_session_factory()
    if factory is None or user_id <= 0:
        return {}
    try:
        with factory() as session:
            return _load_all_for_user_sqlite_fallback(user_id, session)
    except Exception as exc:
        _log.debug("load_user_config_map failed: %s", exc)
        return {}


def get_user_runtime_value(user_id: int, key: str) -> str | None:
    canon = resolve_canonical_key(key)
    if not canon:
        return None
    m = load_user_config_map(user_id)
    v = m.get(canon)
    if v is not None and str(v).strip() != "":
        return str(v).strip()
    return (os.getenv(canon) or "").strip() or None


def _env_with_user_overlay(user_id: int) -> dict[str, str]:
    overlay = load_user_config_map(user_id)
    base = {k: str(v) for k, v in os.environ.items()}
    for k, v in overlay.items():
        if k in ALLOWED_RUNTIME_KEYS and v is not None:
            base[k] = str(v)
    return base


def getenv_for_user(user_id: int, key: str) -> str:
    env = _env_with_user_overlay(user_id)
    return str(env.get(key.upper()) or "").strip()


def set_user_runtime_kv(user_id: int, key: str, value: str) -> dict[str, Any]:
    canon = resolve_canonical_key(key)
    if not canon:
        return {"ok": False, "error": "key_not_allowed", "key": key}
    val = str(value).strip()
    try:
        stored = _encrypt_at_rest(canon, val)
    except RuntimeError as exc:
        return {"ok": False, "error": "fernet_key_required", "detail": str(exc)[:500]}
    try:
        _upsert_pair(user_id, canon, stored)
    except Exception as exc:
        _log.warning("vault upsert failed key=%s err=%s", canon, exc)
        return {"ok": False, "error": "persist_failed", "detail": str(exc)[:300]}
    if _mirror_env_local_enabled() and canon not in ENCRYPT_AT_REST_KEYS:
        merge_env_local_keys({canon: val})
    return {"ok": True, "key": canon, "masked": mask_for_log(canon, val)}


def broker_keys_status_for_user(user_id: int) -> dict[str, Any]:
    """
    Whether live broker credentials look complete for the configured provider.
    Uses user overlay + process env.
    """
    prov = (
        getenv_for_user(user_id, "THIRAMAI_BROKER_PROVIDER")
        or os.getenv("THIRAMAI_BROKER_PROVIDER")
        or "fyers"
    ).strip().lower()
    if prov == "zerodha":
        k_ok = bool(
            getenv_for_user(user_id, "KITE_API_KEY")
            and getenv_for_user(user_id, "KITE_API_SECRET")
            and getenv_for_user(user_id, "KITE_ACCESS_TOKEN")
        )
    else:
        sec = (
            getenv_for_user(user_id, "FYERS_SECRET_KEY")
            or os.getenv("FYERS_SECRET_KEY")
            or os.getenv("FYERS_SECRET")
            or ""
        ).strip()
        k_ok = bool(
            getenv_for_user(user_id, "FYERS_CLIENT_ID")
            and sec
            and getenv_for_user(user_id, "FYERS_ACCESS_TOKEN")
        )
    return {"ok": True, "provider": prov, "configured": k_ok}


def snapshot_public_config(user_id: int) -> dict[str, Any]:
    """Non-secret fields for UI (badges)."""
    m = load_user_config_map(user_id)
    prov = (m.get("THIRAMAI_BROKER_PROVIDER") or os.getenv("THIRAMAI_BROKER_PROVIDER") or "fyers").strip().lower()
    risk = m.get("THIRAMAI_TRADE_RISK_PERCENT") or os.getenv("THIRAMAI_TRADE_RISK_PERCENT") or ""
    capital = m.get("THIRAMAI_TRADING_CAPITAL_INR") or os.getenv("THIRAMAI_TRADING_CAPITAL_INR") or ""
    ss = (m.get("THIRAMAI_SMART_SIZING_ENABLED") or os.getenv("THIRAMAI_SMART_SIZING_ENABLED") or "1").strip()
    sen = (m.get("THIRAMAI_SENTIMENT_OVERLAY_ENABLED") or os.getenv("THIRAMAI_SENTIMENT_OVERLAY_ENABLED") or "1").strip()
    status = broker_keys_status_for_user(user_id)
    return {
        "broker_provider": prov,
        "broker_configured": bool(status.get("configured")),
        "risk_percent_set": bool(str(risk).strip()),
        "capital_inr_set": bool(str(capital).strip()),
        "smart_sizing_enabled": ss not in ("0", "false", "no", "off"),
        "sentiment_overlay_enabled": _sentiment_effective_enabled(user_id, m),
    }


def _parse_iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        raw2 = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw2)
    except Exception:
        return None


def _sentiment_effective_enabled(user_id: int, m: dict[str, str] | None = None) -> bool:
    m = m if m is not None else load_user_config_map(user_id)
    flag = (m.get("THIRAMAI_SENTIMENT_OVERLAY_ENABLED") or os.getenv("THIRAMAI_SENTIMENT_OVERLAY_ENABLED") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        resume = _parse_iso_dt(m.get("THIRAMAI_SENTIMENT_RESUME_AT") or os.getenv("THIRAMAI_SENTIMENT_RESUME_AT"))
        now = datetime.now(timezone.utc)
        if resume and resume <= now:
            return True
        return False
    return True


def sentiment_overlay_active(user_id: int) -> bool:
    return _sentiment_effective_enabled(user_id, None)


def smart_sizing_active(user_id: int) -> bool:
    m = load_user_config_map(user_id)
    v = (m.get("THIRAMAI_SMART_SIZING_ENABLED") or os.getenv("THIRAMAI_SMART_SIZING_ENABLED") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def ist_calendar_date_iso() -> str:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


def _clear_trading_halt_keys(user_id: int) -> None:
    uid = int(user_id)
    try:
        with worker_session_scope() as session:
            for ck in ("THIRAMAI_TRADING_HALT_ACTIVE", "THIRAMAI_TRADING_HALT_IST_DATE"):
                session.execute(
                    text("DELETE FROM user_runtime_config WHERE user_id = :u AND config_key = :k"),
                    {"u": uid, "k": ck},
                )
    except Exception as exc:
        _log.warning("clear trading halt failed uid=%s err=%s", uid, exc)


def is_trading_halted(user_id: int) -> bool:
    """
    PostgreSQL-backed halt for the IST calendar day when set.
    Survives Redis loss and process restarts (checked before Redis in trading_guard).
    """
    uid = int(user_id)
    if uid <= 0:
        return False
    m = load_user_config_map(uid)
    today = ist_calendar_date_iso()
    halt_date = (m.get("THIRAMAI_TRADING_HALT_IST_DATE") or "").strip()
    active = (m.get("THIRAMAI_TRADING_HALT_ACTIVE") or "").strip().lower() in ("1", "true", "yes", "on")
    if not active:
        return False
    if halt_date and today > halt_date:
        _clear_trading_halt_keys(uid)
        return False
    return True


def set_trading_halted_for_ist_session(user_id: int) -> dict[str, Any]:
    """Mark trading halted for the current IST session day (clears automatically next IST calendar day)."""
    d = ist_calendar_date_iso()
    a = set_user_runtime_kv(user_id, "THIRAMAI_TRADING_HALT_ACTIVE", "1")
    b = set_user_runtime_kv(user_id, "THIRAMAI_TRADING_HALT_IST_DATE", d)
    return {"ok": bool(a.get("ok") and b.get("ok")), "ist_date": d}


def set_sentiment_disabled_until_end_of_day_ist(user_id: int) -> dict[str, Any]:
    """Disable sentiment overlay until next IST midnight (approx rollout for 'today')."""
    try:
        from zoneinfo import ZoneInfo

        ist = ZoneInfo("Asia/Kolkata")
        now = datetime.now(ist)
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        resume_utc = nxt.astimezone(timezone.utc).isoformat()
    except Exception:
        resume_utc = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    r1 = set_user_runtime_kv(user_id, "THIRAMAI_SENTIMENT_OVERLAY_ENABLED", "0")
    r2 = set_user_runtime_kv(user_id, "THIRAMAI_SENTIMENT_RESUME_AT", resume_utc)
    return {"ok": bool(r1.get("ok") and r2.get("ok")), "resume_at": resume_utc}
