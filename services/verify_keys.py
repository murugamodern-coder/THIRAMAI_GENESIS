"""
Ping Groq, Tavily, and DigitalOcean APIs; optional DB schema probe + Alembic sync (CLI).

Used by ``build_sre_health_report`` (**External connectivity**) and ``python -m services.verify_keys``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections.abc import Callable
from typing import Any

from core.env_bootstrap import load_project_dotenv, report_env_status

ROOT = Path(__file__).resolve().parents[1]
_VAR = ROOT / "var"
_GROQ_HEARTBEAT_TS = _VAR / "groq_heartbeat_last_thought_ts.txt"

_MISSING_COLUMN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'column\s+"([^"]+)"\s+of\s+relation', re.I),
    re.compile(r'column\s+"([^"]+)"\s+does\s+not\s+exist', re.I),
    re.compile(r"column\s+(\w+)\s+does\s+not\s+exist", re.I),
    re.compile(r"could not find attribute\s+['\"](\w+)['\"]", re.I),
    re.compile(r"no such column:\s*(\S+)", re.I),
    re.compile(r"Unknown column\s+['\"](\w+)['\"]", re.I),
    re.compile(r"undefined column:\s*(\S+)", re.I),
)


def extract_missing_column_from_error(text: str) -> str | None:
    """Best-effort parse of DB error text (PostgreSQL / SQLite / SQLAlchemy)."""
    if not (text or "").strip():
        return None
    for pat in _MISSING_COLUMN_PATTERNS:
        m = pat.search(text)
        if m:
            return str(m.group(1)).strip().strip('"').strip("'") or None
    return None


def ping_groq(*, timeout_sec: float = 15.0) -> dict[str, Any]:
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return {
            "configured": False,
            "ok": None,
            "skipped": True,
            "detail": "GROQ_API_KEY unset",
            "latency_ms": None,
        }
    t0 = time.perf_counter()
    try:
        from groq import Groq

        model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
        client = Groq(api_key=key, timeout=timeout_sec)
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            temperature=0,
        )
        ms = (time.perf_counter() - t0) * 1000.0
        return {
            "configured": True,
            "ok": True,
            "skipped": False,
            "detail": f"chat completion OK ({model})",
            "latency_ms": round(ms, 2),
        }
    except Exception as exc:
        return {
            "configured": True,
            "ok": False,
            "skipped": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "latency_ms": None,
        }


def ping_tavily(*, timeout_sec: float = 15.0) -> dict[str, Any]:
    key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not key:
        return {
            "configured": False,
            "ok": None,
            "skipped": True,
            "detail": "TAVILY_API_KEY unset",
            "latency_ms": None,
        }
    t0 = time.perf_counter()
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=key)
        client.search("connectivity ping", max_results=1)
        ms = (time.perf_counter() - t0) * 1000.0
        return {
            "configured": True,
            "ok": True,
            "skipped": False,
            "detail": "search OK",
            "latency_ms": round(ms, 2),
        }
    except Exception as exc:
        return {
            "configured": True,
            "ok": False,
            "skipped": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "latency_ms": None,
        }


def digitalocean_write_scope_probe(*, timeout_sec: float = 15.0) -> dict[str, Any]:
    """
    Infer whether ``DIGITALOCEAN_TOKEN`` can call write endpoints (e.g. create droplets).

    Sends **POST /v2/droplets** with an intentionally invalid ``image`` id. Read-only tokens
    typically get **403**; write-capable tokens get **422** (validation) without creating a droplet.
    """
    tok = (os.getenv("DIGITALOCEAN_TOKEN") or os.getenv("DO_TOKEN") or "").strip()
    if not tok:
        return {
            "configured": False,
            "skipped": True,
            "write_scope_likely": None,
            "ok": None,
            "detail": "DIGITALOCEAN_TOKEN unset",
            "http_status": None,
        }
    t0 = time.perf_counter()
    try:
        import httpx

        # Invalid image id — must not create a droplet; distinguishes auth + write path from read-only.
        r = httpx.post(
            "https://api.digitalocean.com/v2/droplets",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={
                "name": "thiramai-sre-write-probe",
                "region": "nyc1",
                "size": "s-1vcpu-1gb",
                "image": "thiramai-invalid-image-slug-sre-probe",
            },
            timeout=timeout_sec,
        )
        ms = (time.perf_counter() - t0) * 1000.0
        body_snip = (r.text or "")[:800]
        if r.status_code == 401:
            return {
                "configured": True,
                "skipped": False,
                "write_scope_likely": False,
                "ok": False,
                "detail": "401 Unauthorized — token invalid or expired",
                "http_status": 401,
                "latency_ms": round(ms, 2),
            }
        if r.status_code == 403:
            return {
                "configured": True,
                "skipped": False,
                "write_scope_likely": False,
                "ok": False,
                "detail": f"403 Forbidden — likely read-only token (no write / droplet create). {body_snip}",
                "http_status": 403,
                "latency_ms": round(ms, 2),
            }
        if r.status_code in (400, 404, 422):
            return {
                "configured": True,
                "skipped": False,
                "write_scope_likely": True,
                "ok": True,
                "detail": f"POST /v2/droplets reached validation ({r.status_code}) — write scope likely OK for API.",
                "http_status": r.status_code,
                "latency_ms": round(ms, 2),
            }
        return {
            "configured": True,
            "skipped": False,
            "write_scope_likely": None,
            "ok": False,
            "detail": f"Unexpected HTTP {r.status_code}: {body_snip}",
            "http_status": r.status_code,
            "latency_ms": round(ms, 2),
        }
    except Exception as exc:
        return {
            "configured": True,
            "skipped": False,
            "write_scope_likely": None,
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "http_status": None,
            "latency_ms": None,
        }


def ping_digitalocean(*, timeout_sec: float = 15.0) -> dict[str, Any]:
    tok = (os.getenv("DIGITALOCEAN_TOKEN") or os.getenv("DO_TOKEN") or "").strip()
    if not tok:
        return {
            "configured": False,
            "ok": None,
            "skipped": True,
            "detail": "DIGITALOCEAN_TOKEN unset",
            "latency_ms": None,
        }
    t0 = time.perf_counter()
    try:
        import httpx

        r = httpx.get(
            "https://api.digitalocean.com/v2/account",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=timeout_sec,
        )
        r.raise_for_status()
        ms = (time.perf_counter() - t0) * 1000.0
        return {
            "configured": True,
            "ok": True,
            "skipped": False,
            "detail": "GET /v2/account OK",
            "latency_ms": round(ms, 2),
        }
    except Exception as exc:
        return {
            "configured": True,
            "ok": False,
            "skipped": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "latency_ms": None,
        }


def external_connectivity_report(*, profile: str = "development", timeout_sec: float = 12.0) -> dict[str, Any]:
    """
    Aggregate ping results for SRE **External connectivity** (does not imply Pulse failure by itself).
    ``ok`` is True when every *configured* service responds OK; unconfigured services are skipped.
    """
    _ = profile
    futures: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures["groq"] = pool.submit(ping_groq, timeout_sec=timeout_sec)
        futures["tavily"] = pool.submit(ping_tavily, timeout_sec=timeout_sec)
        futures["digitalocean"] = pool.submit(ping_digitalocean, timeout_sec=timeout_sec)
        services: dict[str, Any] = {}
        for name, fut in futures.items():
            try:
                services[name] = fut.result(timeout=timeout_sec + 5.0)
            except Exception as exc:
                services[name] = {
                    "configured": True,
                    "ok": False,
                    "skipped": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                    "latency_ms": None,
                }
    configured = [s for s in services.values() if s.get("configured")]
    failures = [name for name, s in services.items() if s.get("configured") and s.get("ok") is False]
    if not configured:
        ok = True
        detail = "No external API keys configured — nothing to ping."
    elif not failures:
        ok = True
        detail = f"All configured services reachable ({len(configured)})."
    else:
        ok = False
        detail = "Unreachable: " + ", ".join(failures)

    return {
        "ok": ok,
        "detail": detail,
        "services": services,
        "failures": failures,
        "profile": profile,
    }


def _should_log_groq_heartbeat_thought() -> bool:
    min_sec = float((os.getenv("THIRAMAI_GROQ_HEARTBEAT_THOUGHT_MIN_SEC") or "120").strip() or "120")
    if min_sec <= 0:
        return True
    try:
        _VAR.mkdir(parents=True, exist_ok=True)
        if not _GROQ_HEARTBEAT_TS.is_file():
            return True
        last = float(_GROQ_HEARTBEAT_TS.read_text(encoding="utf-8").strip() or "0")
        return (time.time() - last) >= min_sec
    except (OSError, ValueError):
        return True


def _mark_groq_heartbeat_thought() -> None:
    try:
        _VAR.mkdir(parents=True, exist_ok=True)
        _GROQ_HEARTBEAT_TS.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def groq_heartbeat_hello(*, timeout_sec: float = 20.0, log_thought_on_success: bool = True) -> dict[str, Any]:
    """
    Send user message ``Hello``; on success optionally append assistant reply to ``thought_stream.json``.
    On failure log full API error to the thought stream (rate-limited separately via append_thought).
    """
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key:
        return {
            "configured": False,
            "skipped": True,
            "ok": None,
            "detail": "GROQ_API_KEY unset",
            "reply_preview": None,
            "latency_ms": None,
            "thought_logged": False,
        }
    t0 = time.perf_counter()
    try:
        from groq import Groq

        model = (os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile").strip()
        client = Groq(api_key=key, timeout=timeout_sec)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=128,
            temperature=0.2,
        )
        ms = (time.perf_counter() - t0) * 1000.0
        choice = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        preview = choice[:2000] if choice else "(empty completion)"
        thought_logged = False
        if log_thought_on_success and choice and _should_log_groq_heartbeat_thought():
            try:
                from services.thought_stream import append_thought

                append_thought(
                    f"[External API Heartbeat · Groq] model={model}\n\n{choice}",
                    phase="heartbeat",
                    agent="groq",
                    meta={"source": "external_api_heartbeat", "model": model},
                )
                _mark_groq_heartbeat_thought()
                thought_logged = True
            except Exception:
                pass
        return {
            "configured": True,
            "skipped": False,
            "ok": True,
            "detail": f"Hello completion OK ({model}, {len(choice)} chars)",
            "reply_preview": preview,
            "latency_ms": round(ms, 2),
            "thought_logged": thought_logged,
        }
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        try:
            from services.thought_stream import append_exception_thought

            append_exception_thought(
                exc,
                prefix="[External API Heartbeat · Groq] Hello request failed — full API error:",
                phase="heartbeat",
                agent="groq",
                with_traceback=False,
            )
        except Exception:
            pass
        return {
            "configured": True,
            "skipped": False,
            "ok": False,
            "detail": detail,
            "reply_preview": None,
            "latency_ms": None,
            "thought_logged": False,
        }


def tavily_heartbeat_thiramai(*, timeout_sec: float = 20.0) -> dict[str, Any]:
    """Search ``Thiramai Empire`` and report whether results were returned."""
    key = (os.getenv("TAVILY_API_KEY") or "").strip()
    if not key:
        return {
            "configured": False,
            "skipped": True,
            "ok": None,
            "detail": "TAVILY_API_KEY unset",
            "query": "Thiramai Empire",
            "results_count": None,
            "latency_ms": None,
        }
    query = "Thiramai Empire"
    t0 = time.perf_counter()
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=key)
        raw = client.search(query, max_results=5)
        ms = (time.perf_counter() - t0) * 1000.0
        results = raw.get("results") if isinstance(raw, dict) else None
        n = len(results) if isinstance(results, list) else 0
        ok = n > 0
        return {
            "configured": True,
            "skipped": False,
            "ok": ok,
            "detail": f"{n} result(s) for {query!r}" if ok else f"No results returned for {query!r}",
            "query": query,
            "results_count": n,
            "latency_ms": round(ms, 2),
        }
    except Exception as exc:
        return {
            "configured": True,
            "skipped": False,
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "query": query,
            "results_count": None,
            "latency_ms": None,
        }


def external_api_heartbeat_report(
    *,
    profile: str = "development",
    timeout_sec: float = 20.0,
    log_groq_thought: bool = True,
) -> dict[str, Any]:
    """
    **External API Heartbeat** for SRE: Groq ``Hello`` (+ thought stream), Tavily ``Thiramai Empire``,
    DigitalOcean account read + write-scope probe.
    """
    _ = profile
    futures: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures["groq"] = pool.submit(
            groq_heartbeat_hello, timeout_sec=timeout_sec, log_thought_on_success=log_groq_thought
        )
        futures["tavily"] = pool.submit(tavily_heartbeat_thiramai, timeout_sec=timeout_sec)
        futures["digitalocean_read"] = pool.submit(ping_digitalocean, timeout_sec=timeout_sec)
        futures["digitalocean_write"] = pool.submit(digitalocean_write_scope_probe, timeout_sec=timeout_sec)
        parts: dict[str, Any] = {}
        for name, fut in futures.items():
            try:
                parts[name] = fut.result(timeout=timeout_sec + 8.0)
            except Exception as exc:
                parts[name] = {
                    "configured": True,
                    "ok": False,
                    "skipped": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }

    groq = parts.get("groq") or {}
    tav = parts.get("tavily") or {}
    do_r = parts.get("digitalocean_read") or {}
    do_w = parts.get("digitalocean_write") or {}

    do_read_ok = (not do_r.get("configured")) or do_r.get("skipped") or (do_r.get("ok") is True)
    do_write_ok = (not do_w.get("configured")) or do_w.get("skipped") or (do_w.get("ok") is True)
    digitalocean = {
        "read": do_r,
        "write": do_w,
        "ok": bool(do_read_ok and do_write_ok),
    }

    checks: list[tuple[bool | None, bool]] = []
    for block in (groq, tav, do_r, do_w):
        if not block.get("configured"):
            continue
        if block.get("skipped"):
            continue
        checks.append((block.get("ok"), True))
    configured_ran = [c for c in checks if c[1]]
    oks = [c[0] for c in configured_ran if c[0] is not None]
    overall_ok = bool(configured_ran) and all(c is True for c in oks)

    lines: list[str] = []
    if groq.get("configured") and not groq.get("skipped"):
        lines.append(f"Groq: {'OK' if groq.get('ok') else 'FAIL'} — {str(groq.get('detail') or '')[:120]}")
    if tav.get("configured") and not tav.get("skipped"):
        lines.append(f"Tavily: {'OK' if tav.get('ok') else 'FAIL'} — {tav.get('results_count', 0)} hits")
    if do_r.get("configured") and not do_r.get("skipped"):
        lines.append(f"DO read: {'OK' if do_r.get('ok') else 'FAIL'}")
    if do_w.get("configured") and not do_w.get("skipped"):
        ws = do_w.get("write_scope_likely")
        lines.append(
            f"DO write scope: {'likely YES' if ws is True else 'likely NO' if ws is False else 'unknown'}"
        )

    return {
        "ok": overall_ok if configured_ran else True,
        "detail": " · ".join(lines) if lines else "No external keys configured for heartbeat.",
        "groq": groq,
        "tavily": tav,
        "digitalocean": digitalocean,
        "profile": profile,
    }


def probe_database_schema(*, d_ok: bool) -> dict[str, Any]:
    """
    Lightweight ORM probe against ``organizations``. On failure, extract ``missing_column`` when possible.
    """
    if not d_ok:
        return {
            "ok": True,
            "skipped": True,
            "detail": "skipped (database unreachable)",
            "missing_column": None,
            "error_full": None,
        }
    try:
        from sqlalchemy import select

        from core.database import get_session_factory
        from core.db.models import Organization

        factory = get_session_factory()
        if factory is None:
            return {
                "ok": True,
                "skipped": True,
                "detail": "skipped (DATABASE_URL unset)",
                "missing_column": None,
                "error_full": None,
            }
        with factory() as session:
            session.execute(select(Organization.id).limit(1))
        return {
            "ok": True,
            "skipped": False,
            "detail": "organizations row probe OK",
            "missing_column": None,
            "error_full": None,
        }
    except Exception as exc:
        full = str(exc)
        mc = extract_missing_column_from_error(full)
        return {
            "ok": False,
            "skipped": False,
            "detail": f"{type(exc).__name__}: {full[:600]}",
            "missing_column": mc,
            "error_full": full[:16_000],
            "error_type": type(exc).__name__,
        }


def run_full_schema_sync() -> dict[str, Any]:
    """Run Alembic ``upgrade head`` (same as auto_repair)."""
    from services.auto_repair import run_alembic_upgrade_head

    return run_alembic_upgrade_head()


def repair_modern_corporation_org(*, organization_id: int = 3) -> dict[str, Any]:
    """
    Commit **Modern Corporation** at ``organization_id`` (default 3): create or fix name + tenant defaults.
    """
    from core.database import get_session_factory
    from core.db.provisioning import ensure_modern_corporation_org

    factory = get_session_factory()
    if factory is None:
        return {"ok": False, "error": "DATABASE_URL unset or engine missing", "organization_id": organization_id}
    try:
        with factory() as session:
            with session.begin():
                org = ensure_modern_corporation_org(session, organization_id=int(organization_id))
            oid = int(org.id)
            name = (org.name or "").strip()
        return {
            "ok": True,
            "organization_id": oid,
            "name": name,
            "detail": f"Modern Corporation ensured at id={oid}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "organization_id": organization_id,
        }


def run_master_database_sync(
    *,
    profile: str = "development",
    modern_corporation_org_id: int = 3,
    run_heartbeat: bool = True,
    run_sre_snapshot: bool = True,
    log_thought_stream: bool = True,
    heartbeat_log_groq: bool = True,
    verbose: bool = False,
    verbose_log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    **Master sync** (used by ``python -m services.verify_keys --sync``):

    1. ``alembic upgrade head``
    2. Reset engine cache; repair **Modern Corporation** at org id (default 3)
    3. Probe ``organizations`` schema (missing column hints)
    4. ``external_api_heartbeat_report`` (Groq Hello + Tavily + DO) when ``run_heartbeat``
    5. ``build_sre_health_report`` when ``run_sre_snapshot``
    6. Append human-readable summary to ``thought_stream.json`` when ``log_thought_stream``
    """
    prof = profile if profile in ("development", "production") else "development"
    out: dict[str, Any] = {"ok": True, "profile": prof, "steps": []}
    _vl = verbose_log if verbose_log is not None else print

    def _v(msg: str) -> None:
        if verbose:
            _vl(msg)

    _v("Step 1: Running Alembic upgrade head...")
    alembic = run_full_schema_sync()
    out["alembic"] = alembic
    out["steps"].append({"name": "alembic_upgrade_head", "ok": bool(alembic.get("ok"))})
    if not alembic.get("ok"):
        out["ok"] = False
    _v(f"Step 1 done: alembic ok={bool(alembic.get('ok'))}")

    from core.database import ping_database, reset_engine_cache

    _v("Step 2: Resetting database engine cache...")
    reset_engine_cache()
    _v("Step 2 done: engine cache reset")

    _v(f"Step 3: Repairing Modern Corporation org (id={modern_corporation_org_id})...")
    org_res = repair_modern_corporation_org(organization_id=int(modern_corporation_org_id))
    out["organization_repair"] = org_res
    out["steps"].append({"name": "organization_modern_corporation", "ok": bool(org_res.get("ok"))})
    if not org_res.get("ok"):
        out["ok"] = False
    _v(f"Step 3 done: organization repair ok={bool(org_res.get('ok'))}")

    _v("Step 3b: Syncing PostgreSQL organizations.id sequence...")
    from services.auto_repair import reset_organizations_id_sequence_safe

    seq_res = reset_organizations_id_sequence_safe()
    out["organizations_id_sequence"] = seq_res
    out["steps"].append({"name": "organizations_id_sequence", "ok": bool(seq_res.get("ok", True))})
    _v(f"Step 3b done: {seq_res.get('detail', '')}")

    d_ok = False
    d_msg = ""
    _v("Step 4: Pinging database (SELECT 1 via configured DATABASE_URL)...")
    try:
        d_ok, d_msg = ping_database()
    except Exception as exc:
        d_msg = f"{type(exc).__name__}: {exc}"
    out["database_ping"] = {"ok": d_ok, "detail": d_msg}
    _v(f"Step 4 done: database ping ok={d_ok}")

    _v("Step 5: Probing organizations schema / columns...")
    schema = probe_database_schema(d_ok=d_ok)
    out["database_schema"] = schema
    out["steps"].append({"name": "database_schema_probe", "ok": bool(schema.get("ok"))})
    if not schema.get("ok") and not schema.get("skipped"):
        out["ok"] = False
    _v(f"Step 5 done: schema probe ok={bool(schema.get('ok'))} skipped={bool(schema.get('skipped'))}")

    hb_timeout = max(8.0, min(float((os.getenv("THIRAMAI_SRE_API_HEARTBEAT_TIMEOUT") or "25").strip() or "25"), 90.0))
    if run_heartbeat:
        _v("Step 6: Checking external APIs (Groq, Tavily, DigitalOcean heartbeat)...")
        hb = external_api_heartbeat_report(
            profile=prof,
            timeout_sec=hb_timeout,
            log_groq_thought=heartbeat_log_groq,
        )
        out["external_api_heartbeat"] = hb
        out["steps"].append({"name": "external_api_heartbeat", "ok": bool(hb.get("ok"))})
        _v(f"Step 6 done: external API heartbeat ok={bool(hb.get('ok'))}")
    else:
        _v("Step 6: Skipping external API heartbeat (--no-heartbeat or caller)")
        out["external_api_heartbeat"] = {"skipped": True, "detail": "skipped_by_caller"}

    sre_summary: dict[str, Any] = {}
    if run_sre_snapshot:
        _v("Step 7: Building SRE health report snapshot...")
        from services.sre_health_report import build_sre_health_report

        report = build_sre_health_report(profile=prof, write_reflection=False)
        checks = report.get("checks") or {}
        oi = checks.get("organization_integrity") if isinstance(checks, dict) else None
        oi_detail = (oi or {}).get("detail") if isinstance(oi, dict) else None
        hb_chk = checks.get("external_api_heartbeat") if isinstance(checks, dict) else None
        sre_summary = {
            "pulse_ok": bool(report.get("ok")),
            "failure_reasons": list(report.get("failure_reasons") or []),
            "organization_integrity_ok": bool((oi or {}).get("ok")) if isinstance(oi, dict) else None,
            "organization_integrity_detail": oi_detail,
            "external_api_heartbeat_ok": bool((hb_chk or {}).get("ok")) if isinstance(hb_chk, dict) else None,
            "external_api_heartbeat_detail": (hb_chk or {}).get("detail") if isinstance(hb_chk, dict) else None,
        }
        out["sre"] = sre_summary
        out["steps"].append({"name": "sre_health_snapshot", "ok": bool(report.get("ok"))})
        if not report.get("ok"):
            out["ok"] = False
        _v(f"Step 7 done: SRE report ok={bool(report.get('ok'))}")
    else:
        _v("Step 7: Skipping SRE snapshot (--no-sre or caller)")
        out["sre"] = {"skipped": True}

    if log_thought_stream:
        _v("Step 8: Appending summary to thought_stream.json...")
        alembic_tail = (
            (alembic.get("stderr") or "").strip()
            or (alembic.get("stdout") or "").strip()
            or str(alembic.get("error") or "")
        )[:500]
        lines = [
            "=== Master Sync (verify_keys --sync) ===",
            f"profile={prof}",
            f"Alembic: {'OK' if alembic.get('ok') else 'FAIL'} — {alembic_tail}",
            f"Org repair (id={modern_corporation_org_id}): {'OK' if org_res.get('ok') else 'FAIL'} — {org_res.get('detail') or org_res.get('error', '')}",
            f"DB ping: {'OK' if d_ok else 'FAIL'} — {d_msg[:200]}",
            f"Schema probe: {'OK' if schema.get('ok') else 'FAIL'} — {schema.get('detail', '')}",
        ]
        if schema.get("missing_column"):
            lines.append(f"  missing_column hint: {schema.get('missing_column')}")
        hb_out = out.get("external_api_heartbeat") or {}
        if not hb_out.get("skipped"):
            lines.append(
                f"External API Heartbeat: {'PASS' if hb_out.get('ok') else 'FAIL'} — {hb_out.get('detail', '')}"
            )
            gq = hb_out.get("groq") or {}
            if isinstance(gq, dict) and gq.get("reply_preview"):
                lines.append(f"  Groq reply preview: {str(gq.get('reply_preview'))[:800]}")
        if sre_summary:
            lines.append(
                f"SRE Pulse: {'GREEN' if sre_summary.get('pulse_ok') else 'RED'} — "
                f"reasons={sre_summary.get('failure_reasons')}"
            )
            lines.append(
                f"  organization_integrity: {sre_summary.get('organization_integrity_detail', 'n/a')}"
            )
        msg = "\n".join(lines)[:15_500]
        try:
            from services.thought_stream import append_thought

            append_thought(
                msg,
                phase="master_sync",
                agent="verify_keys",
                meta={"source": "master_database_sync", "overall_ok": bool(out.get("ok"))},
            )
        except Exception:
            pass
        _v("Step 8 done: thought stream updated (or skipped on error)")
    else:
        _v("Step 8: Skipping thought_stream.json (--no-thought or caller)")

    _v(f"Master sync finished: overall ok={bool(out.get('ok'))}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ping external APIs and optionally sync DB schema.")
    parser.add_argument(
        "--sync",
        action="store_true",
        help=(
            "Master database sync: alembic upgrade head, repair Modern Corporation org (default id=3), "
            "schema probe, external API heartbeat, fresh SRE snapshot, log summary to thought_stream.json."
        ),
    )
    parser.add_argument(
        "--sync-org-id",
        type=int,
        default=3,
        help="Organization id for Modern Corporation repair during --sync (default: 3).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON only.")
    args = parser.parse_args(argv)

    # Same as ``master_sync``: load repo-root ``.env`` so DATABASE_URL and API keys exist when using
    # ``python -m services.verify_keys`` (cwd-independent; does not rely on shell env alone).
    if args.json:
        load_project_dotenv()
    else:
        report_env_status()

    ext = external_connectivity_report()
    out: dict[str, Any] = {"external_connectivity": ext}

    if args.sync:
        sync_bundle = run_master_database_sync(
            profile="development",
            modern_corporation_org_id=int(args.sync_org_id),
            run_heartbeat=True,
            run_sre_snapshot=True,
            log_thought_stream=True,
            heartbeat_log_groq=True,
        )
        out["master_sync"] = sync_bundle
        out["alembic"] = sync_bundle.get("alembic")
        out["organization_repair"] = sync_bundle.get("organization_repair")
        out["database_schema"] = sync_bundle.get("database_schema")
        out["external_api_heartbeat"] = sync_bundle.get("external_api_heartbeat")
        out["sre"] = sync_bundle.get("sre")
        out["master_sync_ok"] = bool(sync_bundle.get("ok"))

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print("External connectivity:", "OK" if ext["ok"] else "FAIL", "-", ext["detail"])
        for name, svc in (ext.get("services") or {}).items():
            st = "skip" if svc.get("skipped") else ("OK" if svc.get("ok") else "FAIL")
            print(f"  {name}: {st} — {svc.get('detail', '')}")
        if args.sync:
            ms = out.get("master_sync") or {}
            print("--- Master sync ---")
            print("Alembic:", "OK" if (ms.get("alembic") or {}).get("ok") else "FAIL")
            org = ms.get("organization_repair") or {}
            print("Org repair:", "OK" if org.get("ok") else "FAIL", "-", org.get("detail") or org.get("error", ""))
            ds = ms.get("database_schema") or {}
            print("Schema probe:", ds.get("detail", ""))
            if ds.get("missing_column"):
                print("  missing_column:", ds["missing_column"])
            if ds.get("error_full"):
                print("  error_full:\n", str(ds["error_full"])[:4000])
            hb = ms.get("external_api_heartbeat") or {}
            if not hb.get("skipped"):
                print("External API Heartbeat:", "PASS" if hb.get("ok") else "FAIL", "-", hb.get("detail", ""))
            sr = ms.get("sre") or {}
            if not sr.get("skipped"):
                print("SRE Pulse:", "GREEN" if sr.get("pulse_ok") else "RED")
                print("  failure_reasons:", sr.get("failure_reasons"))
                print("  organization_integrity:", sr.get("organization_integrity_detail", ""))
            print("Thought stream: logged master_sync summary (see /logs/thought_stream.json).")
            print("Master sync overall:", "OK" if ms.get("ok") else "FAIL")

    sync_ok = True
    schema_ok = True
    master_ok = True
    if args.sync:
        ms = out.get("master_sync") or {}
        master_ok = bool(ms.get("ok"))
        sync_ok = bool((ms.get("alembic") or {}).get("ok", True))
        schema_ok = bool((ms.get("database_schema") or {}).get("ok", True))
    return 0 if ext["ok"] and sync_ok and schema_ok and master_ok else 1


if __name__ == "__main__":
    sys.exit(main())
