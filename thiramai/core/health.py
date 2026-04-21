"""
Runtime health snapshot for the autonomous THIRAMAI package (Jarvis core).
"""

from __future__ import annotations

import importlib
from typing import Any

from thiramai.config import (
    MEMORY_FILE,
    THIRAMAI_MODE,
    THIRAMAI_MODE_REQUESTED,
    get_thiramai_mode,
    is_openai_configured,
)
from thiramai.core.executor import Executor


def system_health() -> dict[str, Any]:
    """
    Return coarse readiness: modules importable, memory path writable,
    LLM mode vs key, executor instantiable.
    """
    modules_ok = True
    module_errors: list[str] = []

    for mod in (
        "thiramai.core.planner",
        "thiramai.core.reviewer",
        "thiramai.core.executor",
        "thiramai.integrations.llm_clients",
    ):
        try:
            importlib.import_module(mod)
        except Exception as exc:
            modules_ok = False
            module_errors.append(f"{mod}: {exc}")

    memory_ok = True
    memory_detail = "ok"
    try:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        probe = MEMORY_FILE.parent / ".thiramai_health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        memory_ok = False
        memory_detail = str(exc)

    mode = get_thiramai_mode()
    llm_ok = mode in {"dry-run", "simulation"} or (mode == "live" and is_openai_configured())
    llm_detail = {
        "effective_mode": mode,
        "requested_mode": THIRAMAI_MODE_REQUESTED,
        "openai_configured": is_openai_configured(),
    }

    executor_ok = True
    executor_detail = "ok"
    try:
        Executor()
    except Exception as exc:
        executor_ok = False
        executor_detail = str(exc)

    overall = modules_ok and memory_ok and llm_ok and executor_ok

    return {
        "ok": overall,
        "modules_ok": modules_ok,
        "module_errors": module_errors,
        "memory_ok": memory_ok,
        "memory_detail": memory_detail,
        "memory_file": str(MEMORY_FILE),
        "llm_ok": llm_ok,
        "llm_detail": llm_detail,
        "executor_ok": executor_ok,
        "executor_detail": executor_detail,
        "THIRAMAI_MODE": THIRAMAI_MODE,
    }
