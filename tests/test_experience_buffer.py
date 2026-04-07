"""Feedback loop: experience buffer, autoscale threshold learning, CRITICAL_MISTAKE policy."""

from __future__ import annotations

import json
import time
from datetime import datetime

import services.experience_buffer as eb


def _line(obj: dict) -> str:
    return json.dumps(obj, default=str) + "\n"


def test_adjusted_threshold_lowers_after_recent_failure(tmp_path, monkeypatch) -> None:
    p = tmp_path / "experience_buffer.jsonl"
    now = time.time()
    p.write_text(
        _line(
            {
                "type": "experience",
                "source": "do_worker_autoscale",
                "ts": now,
                "success": False,
                "meta": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", p)
    monkeypatch.setenv("THIRAMAI_AUTOSCALE_PENDING_THRESHOLD", "25")
    monkeypatch.setenv("THIRAMAI_EXPERIENCE_THRESHOLD_STEP", "3")
    eff, expl = eb.adjusted_autoscale_pending_threshold()
    assert eff == 22
    assert "autoscale_failure" in str(expl.get("adjustments"))


def test_adjusted_threshold_cpu_90(tmp_path, monkeypatch) -> None:
    p = tmp_path / "e.jsonl"
    now = time.time()
    p.write_text(
        _line(
            {
                "type": "experience",
                "source": "do_worker_autoscale",
                "ts": now,
                "success": True,
                "meta": {"cpu_pct": 92},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", p)
    monkeypatch.setenv("THIRAMAI_AUTOSCALE_PENDING_THRESHOLD", "25")
    monkeypatch.setenv("THIRAMAI_EXPERIENCE_THRESHOLD_STEP", "3")
    eff, _ = eb.adjusted_autoscale_pending_threshold()
    assert eff == 20


def test_critical_mistake_blocks_until_clear(tmp_path, monkeypatch) -> None:
    p = tmp_path / "e.jsonl"
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", p)
    eb.record_critical_mistake(
        organization_id=7,
        user_id=1,
        tool_id="inventory.sell_stock",
        summary="user said no",
    )
    blocked, reason = eb.is_blocked_by_critical_mistake(7, "inventory.sell_stock")
    assert blocked is True
    assert "CRITICAL_MISTAKE" in reason
    eb.clear_critical_mistake_record(organization_id=7, user_id=1, tool_id="inventory.sell_stock")
    blocked2, _ = eb.is_blocked_by_critical_mistake(7, "inventory.sell_stock")
    assert blocked2 is False


def test_policy_blocks_when_critical_mistake_recorded(tmp_path, monkeypatch) -> None:
    from services.action_policy import PolicyResult, evaluate_tool_action

    p = tmp_path / "e.jsonl"
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", p)
    eb.record_critical_mistake(
        organization_id=99,
        user_id=1,
        tool_id="inventory.read_stock",
        summary="override",
    )
    d = evaluate_tool_action(tool_id="inventory.read_stock", organization_id=99, user_role_level=1)
    assert d.result is PolicyResult.BLOCK
    assert d.metadata.get("critical_mistake") is True


def test_count_successful_experiences(tmp_path, monkeypatch) -> None:
    p = tmp_path / "exp.jsonl"
    p.write_text(
        _line({"type": "experience", "source": "x", "success": True})
        + _line({"type": "experience", "source": "y", "success": False})
        + _line({"type": "reflection", "success": True})
        + _line({"type": "experience", "source": "z", "success": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", p)
    stats = eb.count_successful_experiences(max_scan_lines=10_000)
    assert stats["successful_experience_count"] == 2
    assert stats["truncated"] is False


def test_sre_db_latency_history_filters_window(tmp_path, monkeypatch) -> None:
    now = time.time()
    p = tmp_path / "exp.jsonl"
    old = now - 10 * 86_400
    p.write_text(
        _line(
            {
                "type": "experience",
                "source": "sre_health_check",
                "ts": old,
                "success": True,
                "meta": {"db_latency_ms": 1.0, "profile": "production"},
            }
        )
        + _line(
            {
                "type": "experience",
                "source": "sre_health_check",
                "ts": now - 100,
                "success": True,
                "meta": {"db_latency_ms": 10.0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", p)
    hist = eb.sre_db_latency_history(window_sec=7 * 86_400)
    assert hist == [10.0]


def test_evaluate_db_latency_degraded_when_above_threshold() -> None:
    hist = [10.0, 11.0, 12.0, 10.5, 11.5]
    out = eb.evaluate_db_latency_vs_baseline(80.0, hist, min_samples=5, ratio=2.2, p95_mult=1.2)
    assert out["performance_status"] == "degraded"
    assert out["performance_ok"] is False


def test_predictive_autoscale_monday_morning_lowers_threshold() -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 3, 30, 9, 30, tzinfo=tz)
    out = eb.predictive_autoscale_threshold_adjustment(base_threshold=25, now=now, tz_name="Asia/Kolkata")
    assert "monday_morning" in out["predictive_reasons"]
    assert out["effective_threshold"] < 25
    assert out.get("memory_ratio") == 0.62


def test_predictive_memory_ratio_triggers_extra_drop(monkeypatch) -> None:
    """When slot peak >= base * THIRAMAI_PREDICTIVE_MEMORY_RATIO, threshold drops by memory_drop."""
    from zoneinfo import ZoneInfo

    def _fake_peaks(**_kwargs: object) -> dict[tuple[int, int], float]:
        return {(1, 10): 20.0}

    monkeypatch.setattr(eb, "autoscale_slot_pending_peaks", _fake_peaks)
    monkeypatch.setenv("THIRAMAI_PREDICTIVE_MEMORY_RATIO", "0.62")
    monkeypatch.setenv("THIRAMAI_PREDICTIVE_MEMORY_DROP", "7")
    monkeypatch.setenv("THIRAMAI_PREDICTIVE_GST_DAY_START", "20")
    monkeypatch.setenv("THIRAMAI_PREDICTIVE_GST_DAY_END", "28")
    # Tuesday 2026-01-06 10:00 UTC — outside Monday window; GST env avoids mid-month overlap
    now = datetime(2026, 1, 6, 10, 0, tzinfo=ZoneInfo("UTC"))
    out = eb.predictive_autoscale_threshold_adjustment(base_threshold=25, now=now, tz_name="UTC")
    assert "memory_peak_hour" in out["predictive_reasons"]
    assert out["memory_ratio_triggered"] is True
    assert float(out["memory_ratio"]) == 0.62
    assert int(out["threshold_drop"]) >= 7


def test_build_learning_summary_operational_budget() -> None:
    from services.do_worker_autoscale import _build_learning_summary

    s = _build_learning_summary(
        {
            "action": "noop_operational_budget",
            "threshold_learning": 22,
            "threshold_effective": 16,
            "predictive": {
                "predictive_reasons": ["monday_morning"],
                "threshold_drop": 6,
                "memory_ratio": 0.62,
            },
            "budget_check": {"allow_scale_up": False},
        }
    )
    assert s.startswith("Learning Summary:")
    assert "Monday" in s or "monday" in s.lower()
    assert "lowered the threshold by 6" in s
    assert "budget cap" in s.lower()


def test_autoscale_slot_pending_peaks(tmp_path, monkeypatch) -> None:
    now = time.time()
    p = tmp_path / "exp.jsonl"
    p.write_text(
        _line(
            {
                "type": "experience",
                "source": "do_worker_autoscale",
                "ts": now - 60,
                "success": True,
                "result": {"pending_jobs": 40, "action": "noop_queue_ok"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", p)
    peaks = eb.autoscale_slot_pending_peaks(window_sec=3_600, tz_name="UTC")
    assert len(peaks) >= 1


def test_evaluate_db_latency_healthy_near_baseline() -> None:
    hist = [10.0, 11.0, 12.0, 10.5, 11.5]
    out = eb.evaluate_db_latency_vs_baseline(15.0, hist, min_samples=5)
    assert out["performance_status"] == "healthy"
    assert out["performance_ok"] is True


def test_write_reflection_sre_appends(tmp_path, monkeypatch) -> None:
    exp = tmp_path / "exp.jsonl"
    ref = tmp_path / "ref.jsonl"
    monkeypatch.setattr(eb, "_EXPERIENCE_FILE", exp)
    monkeypatch.setattr(eb, "_REFLECTION_FILE", ref)
    report = {
        "profile": "development",
        "ok": True,
        "checks": {"database": {"ok": True}, "redis": {"ok": False}},
    }
    eb.write_reflection_sre(report=report, exit_ok=True)
    assert ref.is_file()
    lines = ref.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["type"] == "reflection"
    assert row["source"] == "sre_health_check"
