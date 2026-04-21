"""
Integration tests for the `thiramai/` autonomous stack: planner → executor → reviewer
without OPENAI_API_KEY (simulation / dry-run).

Clears `thiramai.*` from sys.modules so config is re-read from monkeypatched env.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _purge_thiramai_modules() -> None:
    for name in list(sys.modules):
        if name == "thiramai" or name.startswith("thiramai."):
            del sys.modules[name]


@pytest.fixture
def thiramai_simulation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("THIRAMAI_MODE", "simulation")
    monkeypatch.setenv("THIRAMAI_DYNAMIC_GOALS", "0")
    _purge_thiramai_modules()
    import thiramai.config  # noqa: F401 — load effective mode from env

    return tmp_path


@pytest.fixture
def thiramai_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("THIRAMAI_MODE", "dry-run")
    monkeypatch.setenv("THIRAMAI_DYNAMIC_GOALS", "0")
    _purge_thiramai_modules()
    import thiramai.config  # noqa: F401


def test_live_without_key_becomes_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("THIRAMAI_MODE", "live")
    _purge_thiramai_modules()
    import thiramai.config as cfg

    assert cfg.get_thiramai_mode() == "dry-run"
    assert cfg.THIRAMAI_MODE_REQUESTED == "live"


def test_system_health(thiramai_simulation: Path) -> None:
    from thiramai.core.health import system_health

    h = system_health()
    assert h["ok"] is True
    assert h["modules_ok"] is True
    assert h["memory_ok"] is True
    assert h["executor_ok"] is True
    assert h["llm_ok"] is True
    assert h["llm_detail"]["effective_mode"] == "simulation"


def test_mock_llm_returns_json_plan() -> None:
    _purge_thiramai_modules()
    from thiramai.integrations.mock_llm import mock_llm

    raw = mock_llm("You are a goal-driven autonomous planner.\nGoal: test-goal\n")
    assert "THIRAMAI_SIMULATION" in raw
    assert "steps" in raw


def test_planner_executor_reviewer_one_cycle(thiramai_simulation: Path) -> None:
    from thiramai.core.memory import MemoryStore
    from thiramai.main import JarvisCore

    engine = JarvisCore(goal="full-system integration test")
    engine.memory = MemoryStore(thiramai_simulation / "memory.json")
    ok = engine.run_one_cycle()
    assert ok is True
    assert engine.latest_results, "expected at least one executed task"
    last = engine.latest_results[-1]
    assert last["review"]["status"] == "pass"
    assert last["result"].get("status") == "success"


def test_dry_run_executor_skips_subprocess(thiramai_dry_run: None, monkeypatch: pytest.MonkeyPatch) -> None:
    import thiramai.core.executor as executor_mod

    def boom(*_a, **_k):  # pragma: no cover
        raise AssertionError("subprocess.run must not be called in dry-run")

    monkeypatch.setattr(executor_mod.subprocess, "run", boom)
    from thiramai.core.executor import Executor

    ex = Executor()
    out = ex.execute_command("echo should-not-run")
    assert out["status"] == "success"
    assert "THIRAMAI_DRY_RUN" in out["output"]
