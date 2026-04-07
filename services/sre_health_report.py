"""
SRE health + scaling intelligence report builder.

Used by ``scripts/sre_health_check.py`` and ``GET /dashboard/live``. Keeps probe logic out of the
FastAPI process import path for scripts while remaining a normal service module.
"""

from __future__ import annotations

import importlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    """
    Load repository-root ``.env`` (same path as ``app.py`` / ``core.env_bootstrap``) and drop any
    cached SQLAlchemy engine so ``DATABASE_URL`` from ``.env`` is picked up.

    Uses ``override=True`` so a stale empty shell variable does not mask ``.env`` values.
    """
    try:
        from core.database import reset_engine_cache
        from core.env_bootstrap import load_project_dotenv

        load_project_dotenv()
        reset_engine_cache()
    except Exception:
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=ROOT / ".env", override=True)
        except ImportError:
            pass


def _nonempty(name: str) -> bool:
    return bool((os.getenv(name) or "").strip())


def _check_imports() -> tuple[bool, list[str]]:
    modules = [
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "httpx",
        "groq",
        "langgraph",
        "tavily",
        "redis",
        "chromadb",
        "docker",
        "apscheduler",
    ]
    failed: list[str] = []
    for m in modules:
        try:
            importlib.import_module(m)
        except ImportError:
            failed.append(m)
    return len(failed) == 0, failed


def _redis_ping() -> tuple[bool, str]:
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return True, "REDIS_URL unset (optional)"
    try:
        import redis

        r = redis.from_url(url, socket_connect_timeout=2.0)
        if r.ping():
            return True, "PONG"
        return False, "ping false"
    except Exception as exc:
        return False, f"{type(exc).__name__}"


def _organization_integrity_self_heal() -> bool:
    """Create ``organizations.id=1`` (Modern Corporation) when the table is empty."""
    try:
        from core.database import get_session_factory
        from core.db.provisioning import ensure_organization_id_one_exists

        factory = get_session_factory()
        if factory is None:
            return False
        with factory() as session:
            with session.begin():
                ensure_organization_id_one_exists(session)
        return True
    except Exception:
        return False


def _organization_count(session: Session) -> int:
    from core.db.models import Organization

    n = session.execute(select(func.count()).select_from(Organization)).scalar_one()
    return int(n or 0)


def _organization_integrity_check(d_ok: bool) -> tuple[bool, str]:
    """
    PASS if any ``organizations`` row exists (``select ... limit 1``). Id 1 is not required.

    Realigns PostgreSQL ``organizations.id`` serial first (fixes drift after explicit-id inserts)
    so provisioning/self-heal and Pulse stay consistent.

    If the table is empty, run ``ensure_organization_id_one_exists`` once and re-check.
    """
    if not d_ok:
        return True, "skipped (database unreachable)"
    try:
        from core.database import get_session_factory
        from core.db.models import Organization
        from core.db.provisioning import sync_organizations_id_sequence

        factory = get_session_factory()
        if factory is None:
            return True, "skipped (DATABASE_URL unset)"

        try:
            with factory() as _seq_sess:
                with _seq_sess.begin():
                    sync_organizations_id_sequence(_seq_sess)
        except Exception:
            pass

        with factory() as session:
            first = session.scalars(select(Organization).limit(1)).first()
            if first is not None:
                ct = _organization_count(session)
                nm = (first.name or "").strip() or "(unnamed)"
                return True, f"{ct} org(s); first id={first.id} ({nm[:44]!r})"

        if _organization_integrity_self_heal():
            with factory() as session:
                first2 = session.scalars(select(Organization).limit(1)).first()
                if first2 is not None:
                    ct2 = _organization_count(session)
                    return True, f"self-heal: seeded default org; {ct2} org(s) now"

        with factory() as session:
            first3 = session.scalars(select(Organization).limit(1)).first()
            if first3 is not None:
                ct3 = _organization_count(session)
                return True, f"{ct3} org(s) after heal"
        return False, "no organizations rows (self-heal failed or DB error)"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:180]}"


def _external_api_keys_check(*, profile: str) -> dict[str, Any]:
    """
    Presence of optional integration keys. **Does not affect Pulse** (``ok`` is always True).

    Missing values surface as ``warnings`` for operators and the live dashboard banner.
    """
    presence = {
        "GROQ_API_KEY": _nonempty("GROQ_API_KEY"),
        "TAVILY_API_KEY": _nonempty("TAVILY_API_KEY"),
        "DIGITALOCEAN_TOKEN": _nonempty("DIGITALOCEAN_TOKEN"),
    }
    warnings: list[str] = []
    if not presence["GROQ_API_KEY"]:
        warnings.append("GROQ_API_KEY missing — NL dashboard / Groq features unavailable.")
    if not presence["TAVILY_API_KEY"]:
        warnings.append("TAVILY_API_KEY missing — live web search context disabled.")
    if not presence["DIGITALOCEAN_TOKEN"]:
        warnings.append("DIGITALOCEAN_TOKEN missing — DigitalOcean autoscale / worker API disabled.")

    return {
        "ok": True,
        "presence": presence,
        "missing": [k for k, v in presence.items() if not v],
        "warnings": warnings,
        "severity": "warning" if warnings else "ok",
        "profile": profile,
    }


def _db_ping() -> tuple[bool, str, float | None]:
    """
    Use the same engine + URL normalization as ``core.database`` so SRE ``d_ok`` matches
    the app session factory (avoids false ``database unreachable`` when only driver prefix differed).
    """
    try:
        from sqlalchemy import text

        from core.database import get_engine

        eng = get_engine()
        if eng is None:
            return False, "DATABASE_URL unset", None
        t0 = time.perf_counter()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        ms = (time.perf_counter() - t0) * 1000.0
        return True, f"ok ({ms:.1f} ms)", ms
    except Exception as exc:
        msg = f"{type(exc).__name__}: {str(exc).strip()[:320]}"
        return False, msg, None


def _db_memory_audit(latency_ms: float | None, d_ok: bool) -> dict[str, Any]:
    window = float((os.getenv("THIRAMAI_SRE_DB_MEMORY_WINDOW_SEC") or str(7 * 86_400)).strip() or str(7 * 86_400))
    min_samples = int((os.getenv("THIRAMAI_SRE_DB_MIN_BASELINE_SAMPLES") or "5").strip() or "5")
    ratio = float((os.getenv("THIRAMAI_SRE_DB_DEGRADE_RATIO") or "2.2").strip() or "2.2")
    p95_mult = float((os.getenv("THIRAMAI_SRE_DB_DEGRADE_P95_MULT") or "1.2").strip() or "1.2")
    floor_d = float((os.getenv("THIRAMAI_SRE_DB_FLOOR_DELTA_MS") or "50").strip() or "50")

    if not d_ok or latency_ms is None:
        return {
            "window_sec": window,
            "window_days": round(window / 86_400, 2),
            "baseline_samples": 0,
            "baseline_median_ms": None,
            "baseline_p95_ms": None,
            "threshold_ms": None,
            "current_latency_ms": None,
            "performance_status": "unavailable",
            "performance_ok": True,
        }

    try:
        from services.experience_buffer import evaluate_db_latency_vs_baseline, sre_db_latency_history

        hist = sre_db_latency_history(window_sec=window)
        return evaluate_db_latency_vs_baseline(
            float(latency_ms),
            hist,
            window_sec=window,
            min_samples=min_samples,
            ratio=ratio,
            p95_mult=p95_mult,
            floor_delta_ms=floor_d,
        )
    except Exception as exc:
        return {
            "window_sec": window,
            "window_days": round(window / 86_400, 2),
            "baseline_samples": 0,
            "performance_status": "memory_read_error",
            "performance_ok": True,
            "error": type(exc).__name__,
        }


def _recovered_wounds(*, profile: str) -> list[dict[str, Any]]:
    if profile != "production":
        return []
    window = float((os.getenv("THIRAMAI_SRE_WOUND_WINDOW_SEC") or str(7 * 86_400)).strip() or str(7 * 86_400))
    wounds: list[dict[str, Any]] = []
    heal_path = ROOT / "var" / "self_heal_last_trigger.txt"
    if heal_path.is_file():
        try:
            last = float(heal_path.read_text(encoding="utf-8").strip())
        except ValueError:
            last = 0.0
        if last > 0 and (time.time() - last) <= window:
            iso = datetime.fromtimestamp(last, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            wounds.append(
                {
                    "component": "infra_self_heal",
                    "kind": "Recovered_Wound",
                    "triggered_at_utc": iso,
                    "age_sec": round(time.time() - last, 1),
                    "summary": (
                        f"Recovered_Wound: infra self-heal last fired at {iso} (replacement worker path); "
                        "system recovered from missing worker heartbeats."
                    ),
                }
            )
    return wounds


_RED_MESSAGES: dict[str, str] = {
    "python_imports": "Heavy Python imports failed",
    "production_required": "Production configuration or secrets incomplete",
    "database_unreachable": "Database unreachable",
    "database_performance_degraded": "Database latency degraded vs 7-day memory baseline",
    "dashboard_template_integrity": "Dashboard live template variable integrity (corporate_identity) failed",
    "organization_integrity": "No organization rows in database (tenant missing)",
}


def _failure_reasons(
    *,
    ok_imp: bool,
    prod_ok: bool,
    profile: str,
    connectivity_ok_for_report: bool,
    d_ok: bool,
    mem_perf_ok: bool,
    dashboard_template_ok: bool = True,
    organization_integrity_ok: bool = True,
) -> list[str]:
    reasons: list[str] = []
    if not ok_imp:
        reasons.append("python_imports")
    if profile == "production" and not prod_ok:
        reasons.append("production_required")
    if not connectivity_ok_for_report:
        reasons.append("database_unreachable")
    if d_ok and not mem_perf_ok:
        reasons.append("database_performance_degraded")
    if not dashboard_template_ok:
        reasons.append("dashboard_template_integrity")
    if not organization_integrity_ok:
        reasons.append("organization_integrity")
    return reasons


def _executive_lines(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if report.get("ok"):
        lines.append("SRE_EXECUTIVE: GREEN | Critical checks passed; infrastructure nominal.")
    else:
        codes = report.get("failure_reasons") or []
        human = [_RED_MESSAGES.get(c, c) for c in codes]
        msg = "; ".join(human) if human else "One or more checks failed"
        lines.append(f"SRE_EXECUTIVE: RED | {msg}")
    for w in report.get("recovered_wounds") or []:
        summ = (w.get("summary") or w.get("component") or "Recovered_Wound").strip()
        lines.append(f"SRE_RECOVERED_WOUND: {summ}")
    return lines


def _autoscale_budget_org_id() -> int:
    for key in ("THIRAMAI_AUTOSCALE_BUDGET_ORG_ID", "THIRAMAI_DEFAULT_ORG_ID"):
        raw = (os.getenv(key) or "").strip()
        if raw.isdigit():
            return int(raw)
    return 0


def _collect_scaling_intelligence() -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False}
    try:
        from services.experience_buffer import (
            adjusted_autoscale_pending_threshold,
            count_successful_experiences,
            predictive_autoscale_threshold_adjustment,
        )

        learned, adjustment = adjusted_autoscale_pending_threshold()
        pred = predictive_autoscale_threshold_adjustment(base_threshold=int(learned))
        exp_stats = count_successful_experiences()
        base_thr = adjustment.get("base_threshold")
        out = {
            "ok": True,
            "base_pending_threshold": base_thr,
            "learned_pending_threshold": int(learned),
            "threshold_learning_adjustments": adjustment.get("adjustments"),
            "predictive_effective_threshold": pred.get("effective_threshold"),
            "predictive_threshold_drop": pred.get("threshold_drop"),
            "predictive_active": bool(pred.get("predictive_active")),
            "predictive_reasons": pred.get("predictive_reasons") or [],
            "predictive_timezone": pred.get("timezone"),
            "successful_experiences": exp_stats,
        }
    except Exception as exc:
        out["error"] = type(exc).__name__
        out["detail"] = str(exc)[:500]

    try:
        from services.economics_service import infra_scaling_budget_remaining

        workers = int((os.getenv("THIRAMAI_SRE_BUDGET_WORKER_COUNT") or "0").strip() or "0")
        bud = infra_scaling_budget_remaining(_autoscale_budget_org_id(), current_worker_nodes=max(0, workers))
        out["infra_budget"] = bud
    except Exception as exc:
        out["infra_budget"] = {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:300]}

    return out


def _scaling_intelligence_console_lines(si: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not si.get("ok"):
        err = si.get("error") or "unknown"
        lines.append(f"SCALING_INTEL: (experience buffer unavailable: {err})")
    else:
        base = si.get("base_pending_threshold")
        learned = si.get("learned_pending_threshold")
        lines.append(f"SCALING_INTEL: Base pending threshold (env): {base}")
        lines.append(f"SCALING_INTEL: Learned pending threshold: {learned}")
        pred_eff = si.get("predictive_effective_threshold")
        drop = si.get("predictive_threshold_drop")
        reasons = si.get("predictive_reasons") or []
        lines.append(
            f"SCALING_INTEL: Predictive effective threshold: {pred_eff} "
            f"(drop {drop}; reasons: {', '.join(reasons) or 'none'})"
        )

    ib = si.get("infra_budget") or {}
    if ib.get("budget_configured"):
        rem = ib.get("remaining_infra_budget_inr")
        cap = ib.get("budget_cap_inr")
        spent = ib.get("estimated_current_infra_inr")
        nodes = ib.get("current_worker_nodes")
        lines.append(
            f"SCALING_INTEL: Remaining infra budget (month est.): INR {rem} "
            f"(cap {cap}; est. spend {spent} for {nodes} worker(s) assumed)"
        )
    elif isinstance(ib, dict) and ib.get("reason"):
        lines.append(f"SCALING_INTEL: Infra budget — {ib.get('reason')}")
    else:
        lines.append("SCALING_INTEL: Infra budget — not reported")

    exp = (si.get("successful_experiences") or {}) if si.get("ok") else {}
    cnt = exp.get("successful_experience_count")
    scanned = exp.get("lines_scanned")
    trunc = exp.get("truncated")
    if cnt is not None:
        tail = f"; buffer scan truncated after {scanned} lines" if trunc else ""
        lines.append(f"SCALING_INTEL: Successful experiences in buffer: {cnt} (lines scanned: {scanned}){tail}")

    if si.get("ok") and si.get("predictive_active"):
        r = ", ".join(si.get("predictive_reasons") or []) or "active"
        lines.append(f"⚡ Predictive Mode Active — {r}")

    return lines


def build_sre_health_report(*, profile: str = "development", write_reflection: bool = False) -> dict[str, Any]:
    """
    Assemble SRE checks + scaling intelligence (same payload as ``scripts/sre_health_check`` JSON).

    ``write_reflection``: when True, append to experience buffer (CLI); keep False for dashboard polls.
    """
    prof = profile if profile in ("development", "production") else "development"
    _load_dotenv()

    report: dict[str, Any] = {"profile": prof, "checks": {}}

    ok_imp, failed = _check_imports()
    report["checks"]["python_imports"] = {"ok": ok_imp, "failed_modules": failed}

    r_ok, r_msg = _redis_ping()
    report["checks"]["redis"] = {"ok": r_ok, "detail": r_msg}

    d_ok, d_msg, d_lat = _db_ping()
    mem = _db_memory_audit(d_lat, d_ok)
    # Development: PASS on successful connection only; baseline / latency degrade does not fail the check.
    # Production: require connection + memory baseline comparison when samples exist.
    if prof != "production":
        database_check_ok = bool(d_ok)
    else:
        database_check_ok = bool(d_ok and mem.get("performance_ok", True))
    report["checks"]["database"] = {
        "ok": database_check_ok,
        "detail": d_msg,
        "latency_ms": round(d_lat, 3) if d_lat is not None else None,
        "memory_audit": mem,
    }

    report["checks"]["env_secrets_present"] = {
        "GROQ_API_KEY": _nonempty("GROQ_API_KEY"),
        "TAVILY_API_KEY": _nonempty("TAVILY_API_KEY"),
        "has_jwt_secret": _nonempty("SECRET_KEY")
        or _nonempty("JWT_SECRET_KEY")
        or _nonempty("JWT_SECRET"),
    }

    report["checks"]["external_api_keys"] = _external_api_keys_check(profile=prof)

    ext_ping_on = (os.getenv("THIRAMAI_SRE_EXTERNAL_CONNECTIVITY") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "skip",
    )
    ext_timeout = float((os.getenv("THIRAMAI_SRE_EXTERNAL_PING_TIMEOUT") or "12").strip() or "12")
    if ext_ping_on:
        try:
            from services.verify_keys import (
                external_api_heartbeat_report,
                external_connectivity_report,
                probe_database_schema,
            )

            report["checks"]["external_connectivity"] = external_connectivity_report(
                profile=prof, timeout_sec=max(3.0, min(ext_timeout, 60.0))
            )
            hb_timeout = max(8.0, min(float((os.getenv("THIRAMAI_SRE_API_HEARTBEAT_TIMEOUT") or "25").strip() or "25"), 90.0))
            hb_log = (os.getenv("THIRAMAI_GROQ_HEARTBEAT_LOG_TO_THOUGHT") or "1").strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )
            report["checks"]["external_api_heartbeat"] = external_api_heartbeat_report(
                profile=prof,
                timeout_sec=hb_timeout,
                log_groq_thought=hb_log,
            )
            report["checks"]["database_schema"] = probe_database_schema(d_ok=d_ok)
        except Exception as exc:
            report["checks"]["external_connectivity"] = {
                "ok": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:240]}",
                "services": {},
                "failures": ["verify_keys_import_or_run"],
                "profile": prof,
            }
            report["checks"]["database_schema"] = {
                "ok": True,
                "skipped": True,
                "detail": f"skipped_after_external_connectivity_error: {type(exc).__name__}",
                "missing_column": None,
                "error_full": None,
            }
            report["checks"]["external_api_heartbeat"] = {
                "ok": False,
                "detail": f"{type(exc).__name__}: {str(exc)[:200]}",
                "groq": {},
                "tavily": {},
                "digitalocean": {},
                "profile": prof,
            }
    else:
        report["checks"]["external_connectivity"] = {
            "ok": True,
            "skipped": True,
            "detail": "THIRAMAI_SRE_EXTERNAL_CONNECTIVITY disabled",
            "services": {},
            "failures": [],
            "profile": prof,
        }
        try:
            from services.verify_keys import probe_database_schema

            report["checks"]["database_schema"] = probe_database_schema(d_ok=d_ok)
        except Exception as exc:
            report["checks"]["database_schema"] = {
                "ok": True,
                "skipped": True,
                "detail": f"{type(exc).__name__}",
                "missing_column": None,
                "error_full": None,
            }
        report["checks"]["external_api_heartbeat"] = {
            "ok": True,
            "skipped": True,
            "detail": "THIRAMAI_SRE_EXTERNAL_CONNECTIVITY disabled — heartbeat skipped",
            "groq": {},
            "tavily": {},
            "digitalocean": {},
            "profile": prof,
        }

    if prof == "production":
        report["checks"]["production_required"] = {
            "DATABASE_URL": _nonempty("DATABASE_URL"),
            "jwt_secret": report["checks"]["env_secrets_present"]["has_jwt_secret"],
            "auth_not_disabled": not (os.getenv("THIRAMAI_AUTH_DISABLED") or "").strip().lower()
            in ("1", "true", "yes", "on"),
        }
        prod_ok = all(report["checks"]["production_required"].values()) and d_ok
    else:
        prod_ok = True

    connectivity_ok_for_report = bool(d_ok or prof != "production")
    mem_perf_ok = bool(not d_ok or mem.get("performance_ok", True))
    if prof != "production" and d_ok:
        # Do not turn Pulse RED in dev solely for latency vs baseline (unavailable or degraded).
        mem_perf_ok = True

    dashboard_template_ok = True
    dashboard_tmpl_detail = "skipped"
    try:
        from services.dashboard_live_context import (
            assert_corporate_identity_template_integrity,
            safe_corporate_identity_for_live_dashboard,
        )

        _dash_snap = safe_corporate_identity_for_live_dashboard()
        dashboard_template_ok, dashboard_tmpl_detail = assert_corporate_identity_template_integrity(_dash_snap)
    except Exception as exc:
        dashboard_template_ok = False
        dashboard_tmpl_detail = f"{type(exc).__name__}: {str(exc)[:360]}"

    report["checks"]["dashboard_template_variable_integrity"] = {
        "ok": bool(dashboard_template_ok),
        "detail": dashboard_tmpl_detail,
    }

    org_int_ok, org_int_detail = _organization_integrity_check(d_ok)
    report["checks"]["organization_integrity"] = {
        "ok": bool(org_int_ok),
        "detail": org_int_detail,
    }

    report["ok"] = bool(
        ok_imp
        and prod_ok
        and connectivity_ok_for_report
        and mem_perf_ok
        and dashboard_template_ok
        and org_int_ok
    )

    report["failure_reasons"] = _failure_reasons(
        ok_imp=ok_imp,
        prod_ok=prod_ok,
        profile=prof,
        connectivity_ok_for_report=connectivity_ok_for_report,
        d_ok=d_ok,
        mem_perf_ok=mem_perf_ok,
        dashboard_template_ok=dashboard_template_ok,
        organization_integrity_ok=org_int_ok,
    )
    report["recovered_wounds"] = _recovered_wounds(profile=prof)
    report["scaling_intelligence"] = _collect_scaling_intelligence()

    if write_reflection:
        try:
            from services.experience_buffer import write_reflection_sre

            write_reflection_sre(report=report, exit_ok=bool(report["ok"]))
        except Exception:
            pass

    return report


__all__ = [
    "ROOT",
    "build_sre_health_report",
    "_load_dotenv",
    "_executive_lines",
    "_scaling_intelligence_console_lines",
]
