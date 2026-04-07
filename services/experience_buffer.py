"""
Feedback loop & structured experience log (append-only JSONL under ``logs/``).

Complements Chroma LTM (``services/ltm_chroma``): this buffer is **deterministic**, fast, and
readable by ``do_worker_autoscale`` for threshold tuning and **predictive** scale windows without embeddings.

Records:
  * **experience** — Action → Result → success/failure (+ optional ``tags``).
  * **reflection** — Post-task notes (SRE health check, autoscale).
  * **CRITICAL_MISTAKE** — Human override; ``action_policy`` blocks repeating the same tool in-org.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_LOG = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_LOGS = _ROOT / "logs"
_EXPERIENCE_FILE = _LOGS / "experience_buffer.jsonl"
_REFLECTION_FILE = _LOGS / "reflection_notes.jsonl"


def _truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


def experience_buffer_enabled() -> bool:
    return not (os.getenv("THIRAMAI_EXPERIENCE_BUFFER_DISABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _ensure_logs() -> None:
    _LOGS.mkdir(parents=True, exist_ok=True)


def _append_line(path: Path, record: dict[str, Any]) -> None:
    if not experience_buffer_enabled():
        return
    _ensure_logs()
    record.setdefault("ts", time.time())
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        _LOG.warning("experience_buffer: append failed %s: %s", path, exc)


def record_experience(
    *,
    source: str,
    action: str,
    result: dict[str, Any],
    success: bool,
    meta: dict[str, Any] | None = None,
    context_key: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Store Action → Result → Success/Failure."""
    _append_line(
        _EXPERIENCE_FILE,
        {
            "type": "experience",
            "source": (source or "")[:128],
            "action": (action or "")[:256],
            "result": result,
            "success": bool(success),
            "meta": meta or {},
            "context_key": (context_key or "")[:256] or None,
            "tags": [t[:64] for t in (tags or [])][:16],
        },
    )


def write_reflection(
    *,
    source: str,
    overall_ok: bool,
    what_went_well: str,
    what_failed: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Self-reflection after SRE / autoscale (and similar) runs."""
    _append_line(
        _REFLECTION_FILE,
        {
            "type": "reflection",
            "source": (source or "")[:128],
            "overall_ok": bool(overall_ok),
            "what_went_well": (what_went_well or "")[:4000],
            "what_failed": (what_failed or "")[:4000],
            "detail": detail or {},
        },
    )


def write_reflection_sre(*, report: dict[str, Any], exit_ok: bool) -> None:
    """Hook for ``scripts/sre_health_check.py``."""
    failed_parts: list[str] = []
    ok_parts: list[str] = []
    checks = report.get("checks") or {}
    for name, body in checks.items():
        if isinstance(body, dict) and "ok" in body:
            if body.get("ok"):
                ok_parts.append(name)
            else:
                failed_parts.append(name)
    write_reflection(
        source="sre_health_check",
        overall_ok=exit_ok,
        what_went_well=", ".join(ok_parts) or "checks completed",
        what_failed=", ".join(failed_parts) or ("none" if exit_ok else "see report detail"),
        detail={"profile": report.get("profile"), "report_ok": report.get("ok")},
    )
    meta: dict[str, Any] = {"profile": report.get("profile")}
    db = (checks.get("database") or {}) if isinstance(checks.get("database"), dict) else {}
    lat = db.get("latency_ms")
    if lat is not None:
        try:
            meta["db_latency_ms"] = float(lat)
        except (TypeError, ValueError):
            pass
    mem = db.get("memory_audit") if isinstance(db.get("memory_audit"), dict) else {}
    if mem.get("performance_status"):
        meta["db_performance_status"] = str(mem.get("performance_status"))[:64]
    record_experience(
        source="sre_health_check",
        action="run",
        result={"exit_ok": exit_ok, "checks": list(checks.keys())},
        success=exit_ok,
        meta=meta,
    )


def sre_db_latency_history(
    *,
    window_sec: float = 604_800.0,
    max_lines: int = 8_000,
) -> list[float]:
    """
    Latencies (ms) from successful SRE runs in the experience buffer within ``window_sec`` (default 7d).

    Used by ``scripts/sre_health_check.py`` to compare current DB probe latency vs recent memory.
    """
    now = time.time()
    rows = _read_tail_jsonl(_EXPERIENCE_FILE, max_lines=max_lines)
    out: list[float] = []
    for row in rows:
        if row.get("type") != "experience":
            continue
        if (row.get("source") or "") != "sre_health_check":
            continue
        if not row.get("success"):
            continue
        ts = float(row.get("ts") or 0)
        if ts and now - ts > window_sec:
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        v = meta.get("db_latency_ms")
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def count_successful_experiences(*, max_scan_lines: int | None = None) -> dict[str, Any]:
    """
    Count ``type=experience`` rows with ``success: true`` in ``experience_buffer.jsonl``.

    Scans from the start of the file up to ``max_scan_lines`` (default from env
    ``THIRAMAI_EXPERIENCE_BUFFER_COUNT_CAP`` or 200_000) to bound work on huge logs.
    """
    if not _EXPERIENCE_FILE.is_file():
        return {
            "successful_experience_count": 0,
            "lines_scanned": 0,
            "truncated": False,
            "note": "experience_buffer.jsonl missing",
        }
    cap_raw = max_scan_lines
    if cap_raw is None:
        cap_raw = int((os.getenv("THIRAMAI_EXPERIENCE_BUFFER_COUNT_CAP") or "200000").strip() or "200000")
    cap = max(1, int(cap_raw))

    n_ok = 0
    scanned = 0
    truncated = False
    try:
        with _EXPERIENCE_FILE.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                scanned += 1
                if scanned > cap:
                    truncated = True
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("type") != "experience":
                    continue
                if row.get("success") is True:
                    n_ok += 1
    except OSError:
        return {
            "successful_experience_count": 0,
            "lines_scanned": scanned,
            "truncated": truncated,
            "note": "read_failed",
        }

    return {
        "successful_experience_count": n_ok,
        "lines_scanned": scanned,
        "truncated": truncated,
    }


def recent_successful_experiences(*, limit: int = 5, max_lines: int = 2_500) -> list[dict[str, Any]]:
    """Last ``limit`` successful ``experience`` rows (newest first), for UI tickers."""
    lim = max(1, min(int(limit), 50))
    rows = _read_tail_jsonl(_EXPERIENCE_FILE, max_lines=max_lines)
    out: list[dict[str, Any]] = []
    for row in reversed(rows):
        if row.get("type") != "experience":
            continue
        if not row.get("success"):
            continue
        res = row.get("result") if isinstance(row.get("result"), dict) else {}
        summary_bits = [str(row.get("source") or ""), str(row.get("action") or "")]
        out.append(
            {
                "ts": row.get("ts"),
                "source": row.get("source"),
                "action": row.get("action"),
                "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
                "summary": " · ".join(s for s in summary_bits if s).strip() or "experience",
                "result_preview": json.dumps(res, ensure_ascii=False, default=str)[:280],
            }
        )
        if len(out) >= lim:
            break
    return out


def evaluate_db_latency_vs_baseline(
    current_ms: float,
    history_ms: list[float],
    *,
    window_sec: float = 604_800.0,
    min_samples: int = 5,
    ratio: float = 2.2,
    p95_mult: float = 1.2,
    floor_delta_ms: float = 50.0,
) -> dict[str, Any]:
    """
    Compare a fresh DB probe latency to historical samples (same order of magnitude as ``history_ms``).

    ``history_ms`` should be prior successful SRE runs (not including *this* run's sample).
    """
    n = len(history_ms)
    base: dict[str, Any] = {
        "window_sec": window_sec,
        "window_days": round(window_sec / 86_400, 2),
        "baseline_samples": n,
        "current_latency_ms": round(float(current_ms), 3),
    }
    if n < max(1, min_samples):
        return {
            **base,
            "baseline_median_ms": None,
            "baseline_p95_ms": None,
            "threshold_ms": None,
            "performance_status": "no_baseline",
            "performance_ok": True,
        }
    s = sorted(history_ms)
    med = float(statistics.median(s))
    idx = max(0, min(len(s) - 1, int(round(0.95 * (len(s) - 1)))))
    p95 = float(s[idx])
    threshold = max(med * ratio, p95 * p95_mult, med + floor_delta_ms)
    degraded = float(current_ms) > threshold
    st = "degraded" if degraded else "healthy"
    return {
        **base,
        "baseline_median_ms": round(med, 3),
        "baseline_p95_ms": round(p95, 3),
        "threshold_ms": round(threshold, 3),
        "performance_status": st,
        "performance_ok": not degraded,
    }


def _read_tail_jsonl(path: Path, max_lines: int = 200) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max(1, min(max_lines, 2000)) :]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _context_bucket(organization_id: int, tool_id: str) -> str:
    return f"org:{int(organization_id)}:tool:{(tool_id or '').strip()[:128]}"


def record_critical_mistake(
    *,
    organization_id: int,
    user_id: int,
    tool_id: str,
    summary: str,
    context_key: str | None = None,
) -> dict[str, Any]:
    """
    User manually overrode / rejected automation — never auto-repeat this tool for this org context.
    """
    ctx = (context_key or "").strip() or _context_bucket(organization_id, tool_id)
    record_experience(
        source="human_feedback",
        action="manual_override",
        result={"tool_id": tool_id, "user_id": int(user_id), "summary": (summary or "")[:2000]},
        success=False,
        meta={"severity": "CRITICAL_MISTAKE"},
        context_key=ctx,
        tags=["CRITICAL_MISTAKE"],
    )
    write_reflection(
        source="human_feedback",
        overall_ok=False,
        what_went_well="",
        what_failed=f"CRITICAL_MISTAKE tagged for context={ctx} tool={tool_id}",
        detail={"organization_id": int(organization_id), "user_id": int(user_id)},
    )
    return {"ok": True, "context_key": ctx}


def is_blocked_by_critical_mistake(organization_id: int, tool_id: str) -> tuple[bool, str]:
    """Newest matching event wins: CRITICAL_CLEAR after CRITICAL_MISTAKE unblocks."""
    oid = int(organization_id)
    tid = (tool_id or "").strip()
    if oid <= 0 or not tid:
        return False, ""
    want = _context_bucket(oid, tid)
    for row in reversed(_read_tail_jsonl(_EXPERIENCE_FILE, max_lines=800)):
        if row.get("type") != "experience":
            continue
        ck = (row.get("context_key") or "").strip()
        if ck != want and not (ck.endswith(f":tool:{tid}") and f"org:{oid}:" in ck):
            continue
        tags = row.get("tags") or []
        if not isinstance(tags, list):
            continue
        if "CRITICAL_CLEAR" in tags:
            return False, ""
        if "CRITICAL_MISTAKE" in tags:
            return True, (
                "This tool was tagged CRITICAL_MISTAKE after a human override for your organization — "
                "automation is blocked until an owner clears it via POST /ai/experience/critical-mistake/clear."
            )
    return False, ""


def clear_critical_mistake_record(
    *,
    organization_id: int,
    user_id: int,
    tool_id: str,
    context_key: str | None = None,
) -> dict[str, Any]:
    ctx = (context_key or "").strip() or _context_bucket(organization_id, tool_id)
    record_experience(
        source="human_feedback",
        action="clear_critical_mistake",
        result={"tool_id": tool_id, "cleared_by": int(user_id)},
        success=True,
        context_key=ctx,
        tags=["CRITICAL_CLEAR"],
    )
    return {"ok": True, "context_key": ctx}


def autoscale_slot_pending_peaks(
    *,
    window_sec: float = 1_209_600.0,
    max_lines: int = 4_000,
    tz_name: str | None = None,
) -> dict[tuple[int, int], float]:
    """
    Max ``pending_jobs`` observed per local (weekday, hour) from ``do_worker_autoscale`` memory.

    Used to pre-scale before queues hit the reactive threshold (e.g. Monday morning, post-pattern).
    """
    tz = ZoneInfo((tz_name or os.getenv("THIRAMAI_AUTOSCALE_TZ") or "Asia/Kolkata").strip() or "Asia/Kolkata")
    now = time.time()
    rows = _read_tail_jsonl(_EXPERIENCE_FILE, max_lines=max_lines)
    peaks: dict[tuple[int, int], float] = {}
    for row in rows:
        if row.get("type") != "experience":
            continue
        if (row.get("source") or "") != "do_worker_autoscale":
            continue
        ts = float(row.get("ts") or 0)
        if not ts or now - ts > window_sec:
            continue
        res = row.get("result") if isinstance(row.get("result"), dict) else {}
        pj = res.get("pending_jobs")
        if pj is None:
            continue
        try:
            pjv = float(pj)
        except (TypeError, ValueError):
            continue
        local = datetime.fromtimestamp(ts, tz=tz)
        key = (local.weekday(), local.hour)
        prev = peaks.get(key, 0.0)
        if pjv > prev:
            peaks[key] = pjv
    return peaks


def predictive_autoscale_threshold_adjustment(
    *,
    base_threshold: int,
    now: datetime | None = None,
    tz_name: str | None = None,
) -> dict[str, Any]:
    """
    Lower the pending threshold **before** load arrives: calendar windows (GST, Monday morning)
    plus feedback-memory peaks for this local weekday/hour.

    ``base_threshold`` should already include experience-buffer learning
    (``adjusted_autoscale_pending_threshold``).
    """
    tz_key = (tz_name or os.getenv("THIRAMAI_AUTOSCALE_TZ") or "Asia/Kolkata").strip() or "Asia/Kolkata"
    tz = ZoneInfo(tz_key)
    if now is None:
        now = datetime.now(tz=tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    try:
        from services.dashboard_ops_state import get_predictive_scaling_mode

        if get_predictive_scaling_mode() == "manual":
            bt = int(base_threshold)
            mem_ratio = float((os.getenv("THIRAMAI_PREDICTIVE_MEMORY_RATIO") or "0.62").strip() or "0.62")
            return {
                "predictive_active": False,
                "predictive_reasons": ["dashboard_manual_mode"],
                "threshold_base_for_predictive": bt,
                "effective_threshold": bt,
                "threshold_drop": 0,
                "memory_slot_peak_pending": None,
                "memory_ratio": mem_ratio,
                "memory_ratio_triggered": False,
                "timezone": tz_key,
            }
    except Exception:
        pass

    cal_drop = int((os.getenv("THIRAMAI_PREDICTIVE_CALENDAR_DROP") or "6").strip() or "6")
    mem_drop = int((os.getenv("THIRAMAI_PREDICTIVE_MEMORY_DROP") or "5").strip() or "5")
    max_total_drop = int((os.getenv("THIRAMAI_PREDICTIVE_MAX_THRESHOLD_DROP") or "18").strip() or "18")
    mem_ratio = float((os.getenv("THIRAMAI_PREDICTIVE_MEMORY_RATIO") or "0.62").strip() or "0.62")
    floor_t = int((os.getenv("THIRAMAI_EXPERIENCE_THRESHOLD_FLOOR") or "5").strip() or "5")

    reasons: list[str] = []
    m_start = int((os.getenv("THIRAMAI_PREDICTIVE_MONDAY_START_HOUR") or "8").strip() or "8")
    m_end = int((os.getenv("THIRAMAI_PREDICTIVE_MONDAY_END_HOUR") or "12").strip() or "12")
    gst_start = int((os.getenv("THIRAMAI_PREDICTIVE_GST_DAY_START") or "11").strip() or "11")
    gst_end = int((os.getenv("THIRAMAI_PREDICTIVE_GST_DAY_END") or "17").strip() or "17")

    cal_active = False
    if now.weekday() == 0 and m_start <= now.hour < m_end:
        reasons.append("monday_morning")
        cal_active = True
    if gst_start <= now.day <= gst_end:
        reasons.append("gst_filing_window")
        cal_active = True

    drop = cal_drop if cal_active else 0

    slot_peak: float | None = None
    try:
        peaks = autoscale_slot_pending_peaks(tz_name=tz_key)
        slot_peak = peaks.get((now.weekday(), now.hour))
        if slot_peak is not None and slot_peak >= base_threshold * mem_ratio:
            reasons.append("memory_peak_hour")
            drop += mem_drop
    except Exception as exc:
        _LOG.debug("predictive_autoscale: memory peaks skipped %s", exc)

    drop = min(drop, max_total_drop)
    effective = max(floor_t, int(base_threshold) - drop)
    predictive_active = len(reasons) > 0 and drop > 0
    memory_ratio_triggered = (
        "memory_peak_hour" in reasons
        and slot_peak is not None
        and float(slot_peak) >= float(base_threshold) * float(mem_ratio)
    )

    return {
        "predictive_active": predictive_active,
        "predictive_reasons": reasons,
        "threshold_base_for_predictive": int(base_threshold),
        "effective_threshold": effective,
        "threshold_drop": drop,
        "memory_slot_peak_pending": slot_peak,
        "memory_ratio": mem_ratio,
        "memory_ratio_triggered": memory_ratio_triggered,
        "timezone": tz_key,
    }


def adjusted_autoscale_pending_threshold() -> tuple[int, dict[str, Any]]:
    """
    Read recent autoscale experiences; lower pending threshold after failures or high CPU stress hints.

    Env base: ``THIRAMAI_AUTOSCALE_PENDING_THRESHOLD`` (default 25).
    """
    base = int((os.getenv("THIRAMAI_AUTOSCALE_PENDING_THRESHOLD") or "25").strip() or "25")
    floor = int((os.getenv("THIRAMAI_EXPERIENCE_THRESHOLD_FLOOR") or "5").strip() or "5")
    step = int((os.getenv("THIRAMAI_EXPERIENCE_THRESHOLD_STEP") or "3").strip() or "3")
    window_sec = float((os.getenv("THIRAMAI_EXPERIENCE_WINDOW_SEC") or "604800").strip() or "604800")  # 7d
    now = time.time()
    explanation: dict[str, Any] = {
        "base_threshold": base,
        "adjustments": [],
    }
    effective = base
    for row in reversed(_read_tail_jsonl(_EXPERIENCE_FILE, max_lines=300)):
        if row.get("type") != "experience":
            continue
        if (row.get("source") or "") != "do_worker_autoscale":
            continue
        ts = float(row.get("ts") or 0)
        if now - ts > window_sec:
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        cpu = meta.get("cpu_pct")
        if cpu is not None:
            try:
                cpu_f = float(cpu)
                if cpu_f >= 90:
                    delta = max(step, 5)
                    effective -= delta
                    explanation["adjustments"].append(f"high_cpu_{cpu_f:.0f}%:-{delta}")
                elif cpu_f >= 70:
                    delta = step
                    effective -= delta
                    explanation["adjustments"].append(f"elevated_cpu_{cpu_f:.0f}%:-{delta}")
            except (TypeError, ValueError):
                pass
        if row.get("success") is False:
            effective -= step
            explanation["adjustments"].append("autoscale_failure:-%s" % step)
        tags = row.get("tags") or []
        if isinstance(tags, list) and "scale_earlier" in tags:
            effective -= step
            explanation["adjustments"].append("tag_scale_earlier:-%s" % step)

    effective = max(floor, int(effective))
    explanation["effective_threshold"] = effective
    return effective, explanation


def finalize_autoscale_run(out: dict[str, Any], *, cpu_pct: float | None = None) -> None:
    """Record outcome + reflection for one ``run_autoscale_once`` call."""
    action = str(out.get("action") or "run")
    ok = True
    if out.get("error"):
        ok = False
    elif action == "create_failed":
        ok = False
    elif isinstance(out.get("create"), dict) and not out["create"].get("ok"):
        ok = False
    meta: dict[str, Any] = {}
    raw_cpu = cpu_pct
    if raw_cpu is None and (os.getenv("THIRAMAI_LAST_HOST_CPU_PCT") or "").strip():
        try:
            raw_cpu = float((os.getenv("THIRAMAI_LAST_HOST_CPU_PCT") or "").strip())
        except ValueError:
            raw_cpu = None
    if raw_cpu is not None:
        meta["cpu_pct"] = float(raw_cpu)
    tags: list[str] = []
    if (not ok and action == "create_failed") or (
        isinstance(out.get("create"), dict) and not out["create"].get("ok")
    ):
        tags.append("scale_earlier")
    if out.get("scale_mode") == "predictive":
        tags.append("predictive_scale")
    elif out.get("action") == "scaled_up" and out.get("scale_mode") == "reactive":
        tags.append("reactive_scale")
    for t in out.get("experience_tags") or []:
        if isinstance(t, str) and t.strip():
            tags.append(t.strip()[:64])
    record_experience(
        source="do_worker_autoscale",
        action=action,
        result={k: v for k, v in out.items() if k != "create"},
        success=bool(ok),
        meta=meta,
        tags=tags,
    )
    went = []
    failed = []
    if out.get("action") == "scaled_up":
        mode = out.get("scale_mode") or "reactive"
        went.append(f"provisioned worker droplet ({mode})")
    elif out.get("action") in (
        "noop_queue_ok",
        "noop_at_cap",
        "noop_cooldown",
        "noop_operational_budget",
        "noop_budget_check_error",
    ):
        went.append(out["action"])
    elif out.get("skipped"):
        went.append(str(out.get("reason", "skipped")))
    if out.get("error"):
        failed.append(str(out["error"])[:500])
    if out.get("create") and not (out.get("create") or {}).get("ok"):
        failed.append("droplet create failed")
    write_reflection(
        source="do_worker_autoscale",
        overall_ok=not failed,
        what_went_well="; ".join(went) or "cycle complete",
        what_failed="; ".join(failed) or "none",
        detail={
            "pending": out.get("pending_jobs"),
            "threshold_used": out.get("threshold_effective"),
            "scale_mode": out.get("scale_mode"),
            "predictive_reasons": (out.get("predictive") or {}).get("predictive_reasons"),
            "learning_summary": out.get("learning_summary"),
        },
    )


def maybe_mirror_to_chroma(
    *,
    organization_id: int,
    prompt_context: str,
    tool_id: str,
    action: dict[str, Any],
    outcome_ok: bool,
) -> None:
    """Optional: duplicate key experiences into Chroma LTM."""
    if not _truthy("THIRAMAI_EXPERIENCE_LTM_MIRROR"):
        return
    try:
        from services import ltm_chroma

        ltm_chroma.record_tool_execution(
            organization_id=int(organization_id),
            prompt_context=prompt_context[:4000],
            tool_id=tool_id,
            action=action,
            outcome_ok=outcome_ok,
            error_message="" if outcome_ok else "experience_buffer mirror",
        )
    except Exception as exc:
        _LOG.debug("experience_buffer: chroma mirror skipped %s", exc)


def recent_experience_entries(
    *,
    organization_id: int | None = None,
    limit: int = 20,
    max_scan_lines: int = 2000,
) -> list[dict[str, Any]]:
    """
    Tail-scan ``experience_buffer.jsonl``. With ``organization_id``, keep rows tagged ``org:{id}``
    or carrying ``meta.organization_id`` (written by autonomous / orchestrator hooks).
    """
    rows = _read_tail_jsonl(_EXPERIENCE_FILE, max_lines=max_scan_lines)
    want_org = int(organization_id) if organization_id is not None and int(organization_id) > 0 else 0
    tag_need = f"org:{want_org}" if want_org else ""
    picked: list[dict[str, Any]] = []
    for r in reversed(rows):
        if r.get("type") != "experience":
            continue
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        tags = r.get("tags") if isinstance(r.get("tags"), list) else []
        if want_org > 0:
            mo = meta.get("organization_id")
            try:
                mo_i = int(mo) if mo is not None else 0
            except (TypeError, ValueError):
                mo_i = 0
            tag_match = tag_need in [str(t) for t in tags]
            if mo_i != want_org and not tag_match:
                continue
        picked.append(
            {
                "ts": r.get("ts"),
                "source": r.get("source"),
                "action": r.get("action"),
                "success": r.get("success"),
            }
        )
        if len(picked) >= limit:
            break
    return picked


def recent_strategy_outcomes(
    *,
    organization_id: int,
    decision_key: str,
    limit: int = 20,
    max_scan_lines: int = 4000,
) -> list[dict[str, Any]]:
    """Tail-scan for ``source=strategy_memory`` rows with ``meta.decision_key`` (confidence tuning)."""
    oid = int(organization_id)
    key = (decision_key or "").strip()
    if oid <= 0 or not key:
        return []
    rows = _read_tail_jsonl(_EXPERIENCE_FILE, max_lines=max_scan_lines)
    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        if r.get("type") != "experience":
            continue
        if (r.get("source") or "") != "strategy_memory":
            continue
        meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
        try:
            mo = int(meta.get("organization_id") or 0)
        except (TypeError, ValueError):
            mo = 0
        if mo != oid:
            continue
        if str(meta.get("decision_key") or "") != key:
            continue
        out.append(
            {
                "ts": r.get("ts"),
                "success": bool(r.get("success")),
                "action": r.get("action"),
                "result": r.get("result") if isinstance(r.get("result"), dict) else {},
            }
        )
        if len(out) >= limit:
            break
    return out


def stable_context_hash(*parts: str) -> str:
    """Short hash for dedupe keys in clients."""
    h = hashlib.sha256("|".join(parts).encode("utf-8", errors="replace")).hexdigest()[:24]
    return h
