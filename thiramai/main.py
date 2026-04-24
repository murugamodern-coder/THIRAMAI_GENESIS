import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
import argparse
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path so `python thiramai/main.py` resolves `thiramai.*` imports.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_rp = str(_REPO_ROOT)
if _rp not in sys.path:
    sys.path.insert(0, _rp)

from thiramai.config import (
    THIRAMAI_DYNAMIC_GOALS,
    THIRAMAI_EMERGENCY_STOP_FILE,
    THIRAMAI_EVENT_DELTA_THRESHOLD,
    THIRAMAI_GOAL,
    THIRAMAI_LOCATION,
    THIRAMAI_LOOP_SLEEP_SEC,
    THIRAMAI_MAX_CONSECUTIVE_CYCLE_FAILURES,
    THIRAMAI_MAX_FIX_RETRIES,
    THIRAMAI_MAX_LOOP_ITERATIONS,
    THIRAMAI_MAX_TASKS_PER_CYCLE,
    THIRAMAI_MAX_TASKS_PER_JOB,
    THIRAMAI_MODE_REQUESTED,
    effective_parallel_shell_enabled,
    THIRAMAI_FOREVER_HARD_CAP_ITERATIONS,
    THIRAMAI_WATCHDOG_MAX_SECONDS,
    THIRAMAI_STOP_FOREVER_ON_CLEAN_CYCLE,
    get_thiramai_mode,
)
from thiramai.core.health import system_health
from thiramai.core.agent_factory import AgentFactory
from thiramai.core.device_controller import DeviceController
from thiramai.core.executor import Executor, PolicyViolationError, UnsafeCommandError
from thiramai.core.logger import SecurityLogger
from thiramai.core.memory import MemoryStore
from thiramai.core.planner import Planner
from thiramai.core.reviewer import Reviewer
from thiramai.core.task_waves import tasks_to_waves, wave_eligible_for_parallel_shell
from thiramai.core.telemetry import SessionTelemetry
from thiramai.core.goal_engine import generate_goals, get_resource_snapshot, select_active_goal
from thiramai.core.self_healing import SelfHealer
from thiramai.core.system_awareness import system_scan_compact
from thiramai.integrations.market import get_market_prices
from thiramai.integrations.system_metrics import get_system_status
from thiramai.integrations.weather import get_weather


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
_loop_log = logging.getLogger("thiramai.loop")
_telemetry = logging.getLogger("thiramai.telemetry")
_cli_log = logging.getLogger("thiramai.cli")


def _ensure_runtime_dirs(base_dir: Path | None = None) -> dict[str, Path]:
    root = (base_dir or _REPO_ROOT).resolve()
    paths = {
        "logs": root / "logs",
        "knowledge": root / "knowledge",
        "runtime": root / "runtime",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def _log_debug_event(tag: str, payload: dict[str, Any]) -> None:
    _loop_log.debug("%s %s", tag, json.dumps(payload, ensure_ascii=True))


def _effective_tasks_per_cycle_cap() -> int:
    """Minimum of configured per-cycle and per-job caps when either is set (>0)."""
    caps = [x for x in (THIRAMAI_MAX_TASKS_PER_CYCLE, THIRAMAI_MAX_TASKS_PER_JOB) if x and x > 0]
    return min(caps) if caps else 0


class JarvisCore:
    def __init__(self, goal: str, *, fixed_goal_only: bool = False, job_id: str | None = None) -> None:
        self._seed_goal = goal
        self.job_id = job_id
        self.goal = goal
        self._fixed_goal_only = bool(fixed_goal_only)
        self.planner = Planner()
        self.executor = Executor()
        self.reviewer = Reviewer()
        self.memory = MemoryStore()
        self.factory = AgentFactory()
        self.device_controller = DeviceController()
        self.latest_results: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.last_context: dict[str, Any] | None = None
        self.execution_deadline: float | None = None
        self.stop_event = threading.Event()
        self._last_cycle_clean = False
        self._last_cycle_deadline = False
        self._result_lock = threading.Lock()
        self.security_logger = SecurityLogger()
        self.telemetry = SessionTelemetry()

    def request_stop(self) -> None:
        """Signal the current / next autonomous cycle to abort between steps."""
        self.stop_event.set()

    def _should_abort_cycle(self) -> bool:
        if self.stop_event.is_set():
            return True
        if self.execution_deadline is not None and time.time() >= self.execution_deadline:
            return True
        stop_file = (THIRAMAI_EMERGENCY_STOP_FILE or "").strip()
        if stop_file:
            try:
                if Path(stop_file).expanduser().exists():
                    return True
            except OSError:
                pass
        if self.job_id:
            try:
                from thiramai.runtime import goal_jobs

                if goal_jobs.poll_job_control(self.job_id) == "cancel":
                    self.stop_event.set()
                    return True
            except Exception:
                pass
        return False

    def _wait_while_paused(self) -> None:
        """Block between task waves when job is paused via ops API / SQLite."""
        if not self.job_id:
            return
        from thiramai.runtime import goal_jobs

        while True:
            sig = goal_jobs.poll_job_control(self.job_id)
            if sig == "cancel":
                self.stop_event.set()
                return
            if sig != "pause":
                return
            time.sleep(0.35)

    def _task_stability_priority(self, task: dict[str, Any]) -> Any:
        from core.stability.task_priority import TaskPriority

        tier = str(task.get("tier", "normal")).lower()
        if tier == "critical":
            return TaskPriority.CRITICAL
        if tier == "optional":
            return TaskPriority.OPTIONAL
        return TaskPriority.NORMAL

    def _approval_gate_result(self, task: dict[str, Any], cycle_id: int, task_id: str) -> dict[str, Any] | None:
        if str(task.get("risk_level", "low")).lower() != "high":
            return None
        from thiramai.config import THIRAMAI_APPROVAL_TIMEOUT_SEC
        from thiramai.runtime import approval_store

        aid = approval_store.enqueue_high_risk_task(
            task=task,
            cycle_id=cycle_id,
            task_id=task_id,
            goal=self.goal,
        )
        self.memory.append(
            "approval_requested",
            {"approval_id": aid, "task_id": task_id, "cycle_id": cycle_id, "goal": self.goal},
        )
        w = approval_store.wait_for_approval(aid, timeout_sec=THIRAMAI_APPROVAL_TIMEOUT_SEC)
        if w.get("ok"):
            return None
        reason = str(w.get("reason", "approval_denied"))
        return {
            "status": "blocked",
            "returncode": -1,
            "output": "",
            "error": reason,
            "ok": False,
            "stdout": "",
            "stderr": reason,
            "exit_code": -1,
        }

    def _step_record_and_branch(
        self,
        cycle_id: int,
        task_id: str,
        task: dict[str, Any],
        result: dict[str, Any],
        review: dict[str, Any],
        learning_snapshot: dict[str, Any],
        cycle_dirty_box: list[bool],
    ) -> None:
        task["result_history"].append({"result": result, "review": review})

        record = {
            "cycle_id": cycle_id,
            "task_id": task_id,
            "task": task,
            "result": result,
            "review": review,
        }
        with self._result_lock:
            self.latest_results.append(record)
        self.memory.append("result", record)
        _log_debug_event("[STEP RESULT]", record)
        self.telemetry.record_llm_confidence(review.get("confidence"))

        if review.get("status") == "pass":
            task["status"] = "success"
            return

        cycle_dirty_box[0] = True
        task["status"] = "failed"
        failure_type = str(review.get("failure_type", "invalid_output"))
        fail_record = self._attempt_fix(task, result, review, cycle_id, task_id)
        self.failures.append(fail_record)
        self.memory.append("failure", fail_record)

        capability_gap = self.factory.detect_capability_gap(task, result, review)
        if capability_gap:
            generated = self.factory.expand_capability(
                agent_type=str(capability_gap["agent_type"]),
                purpose=str(capability_gap["purpose"]),
            )
            self.memory.append(
                "capability_expansion",
                {
                    "cycle_id": cycle_id,
                    "task_id": task_id,
                    "task": task,
                    "capability_gap": capability_gap,
                    "generated_agent": generated,
                },
            )
            self._retry_with_generated_agent(
                cycle_id=cycle_id,
                task_id=task_id,
                task=task,
                parent_result=result,
                generated_type=str(capability_gap["agent_type"]),
            )

        _loop_log.info("[REPLAN TRIGGERED] task_id=%s cycle_id=%s", task_id, cycle_id)
        replan = self.planner.replan(
            goal=self.goal,
            failed_step=task,
            failure_type=failure_type,
            result=result,
            past_failures=self.failures[-20:],
            learning_snapshot=learning_snapshot,
        )
        self.memory.append(
            "replan",
            {
                "cycle_id": cycle_id,
                "task_id": task_id,
                "failure_type": failure_type,
                "replan": replan,
            },
        )
        _log_debug_event("[PLAN CREATED]", {"cycle_id": cycle_id, "task_id": task_id, "replan": replan})
        self._execute_replan(cycle_id, task_id, replan)

    def _audit_execution(self, *, cycle_id: int, task_id: str, task: dict[str, Any], result: dict[str, Any]) -> None:
        command = str(task.get("command", "")).strip()
        policy_decision = result.get("policy_decision")
        if not isinstance(policy_decision, dict):
            policy_decision = {
                "allow": str(result.get("status", "")).lower() != "blocked",
                "policy_id": "unknown",
                "reason": str(result.get("error", "")),
            }
        status = str(result.get("status", "unknown"))
        risk_level = str(task.get("risk_level", "low"))
        self.security_logger.log(
            cycle_id=cycle_id,
            task_id=task_id,
            command=command,
            policy_decision=policy_decision,
            execution_status=status,
            risk_level=risk_level,
        )
        self.telemetry.record_execution(
            executed=bool(command),
            blocked=status == "blocked",
            status=status,
            blocked_reason=str(policy_decision.get("reason", "")),
        )

    def _run_single_task_step(
        self,
        cycle_id: int,
        task: dict[str, Any],
        learning_snapshot: dict[str, Any],
        cycle_dirty_box: list[bool],
    ) -> None:
        from thiramai.runtime import ai_observability

        if not task.get("type"):
            task["type"] = "analysis"
        task_id = f"{cycle_id}-{task.get('_plan_order', 0)}"
        self.telemetry.set_runtime_status(
            goal=self.goal,
            cycle_id=cycle_id,
            task=f"{task.get('type', 'unknown')}: {str(task.get('description', ''))[:80]}",
        )
        ai_observability.record_step()
        _log_debug_event("[STEP START]", {"task_id": task_id, "step": task})
        blocked = self._approval_gate_result(task, cycle_id, task_id)
        if blocked is not None:
            result = blocked
            result.setdefault(
                "policy_decision",
                {"allow": False, "policy_id": "approval_gate.blocked", "reason": str(result.get("error", "approval blocked"))},
            )
        else:
            try:
                result = self._execute_task(task)
            except (PolicyViolationError, UnsafeCommandError) as exc:
                result = {
                    "status": "blocked",
                    "returncode": -1,
                    "output": "",
                    "error": str(exc),
                    "ok": False,
                    "stdout": "",
                    "stderr": str(exc),
                    "exit_code": -1,
                    "policy_decision": {
                        "allow": False,
                        "policy_id": getattr(exc, "policy_id", type(exc).__name__),
                        "reason": getattr(exc, "reason", str(exc)),
                    },
                }
        self._audit_execution(cycle_id=cycle_id, task_id=task_id, task=task, result=result)
        _log_debug_event(
            "[DECISION MADE]",
            {"task_id": task_id, "decision_type": task.get("type"), "result_status": result.get("status")},
        )
        review = self.reviewer.review(task, result)
        self._step_record_and_branch(cycle_id, task_id, task, result, review, learning_snapshot, cycle_dirty_box)

    def _minimal_realtime_context(self) -> dict[str, Any]:
        return {
            "system_status": {
                "disk_free_ratio": 0.5,
                "disk_free_gb": 10.0,
                "note": "stub (non-live mode)",
            },
            "external_data": {
                "weather": {"stub": True, "location": THIRAMAI_LOCATION},
                "market": {"stub": True},
                "soil_moisture": 0.5,
            },
            "recent_failures": self._recent_failures_from_memory(limit=5),
        }

    def _log_health_compact(self) -> None:
        h = system_health()
        _loop_log.info(
            "[HEALTH] ok=%s modules=%s memory=%s llm=%s executor=%s",
            h.get("ok"),
            h.get("modules_ok"),
            h.get("memory_ok"),
            h.get("llm_ok"),
            h.get("executor_ok"),
        )

    def run_one_cycle(self) -> bool:
        """Run exactly one autonomous cycle (no sleep). For tests and tooling."""
        self._log_health_compact()
        cycle_id = int(time.time())
        _loop_log.info("[LOOP ITERATION] single_shot cycle_id=%s", cycle_id)
        return self._run_autonomous_cycle(cycle_id)

    def _run_autonomous_cycle(self, cycle_id: int) -> bool:
        _loop_log.info("Starting autonomous cycle for goal: %s", self.goal)
        cycle_started_at = time.monotonic()
        self.telemetry.set_runtime_status(goal=self.goal, cycle_id=cycle_id, task="planning")
        try:
            resources = get_resource_snapshot()
            self.memory.append("resources", {"cycle_id": cycle_id, "resources": resources})

            past_failures = self._recent_failures_from_memory(limit=20)
            learning_snapshot = self.memory.get_learning_snapshot()
            awareness = system_scan_compact()

            if THIRAMAI_DYNAMIC_GOALS and not self._fixed_goal_only:
                goal_candidates = generate_goals(
                    {
                        "seed_goal": self._seed_goal,
                        "learning": learning_snapshot,
                        "awareness": awareness,
                        "recent_failures": past_failures[-12:],
                        "resources": resources,
                    }
                )
                ranked = goal_candidates
                self.goal, goal_meta = select_active_goal(ranked, resources)
                _log_debug_event("[PRIORITY QUEUE]", {"goals": ranked[:8], "resources": resources})
                _log_debug_event("[GOAL SELECTED]", {"active_goal": self.goal, "meta": goal_meta})
                self.memory.append(
                    "goal_selection",
                    {
                        "cycle_id": cycle_id,
                        "active_goal": self.goal,
                        "meta": goal_meta,
                        "resources": resources,
                    },
                )
            else:
                self.goal = self._seed_goal

            cycle_dirty = False
            deadline_stopped = False
            self._cycle_quality_dirty = False

            realtime_context = self._collect_realtime_context()
            realtime_context["resources"] = resources
            realtime_context["sovereign_goal_seed"] = self._seed_goal
            _log_debug_event("[REAL DATA RECEIVED]", realtime_context)

            plan = self.planner.create_plan(
                self.goal,
                past_failures=past_failures,
                learning_snapshot=learning_snapshot,
                realtime_context=realtime_context,
            )
            if bool(plan.get("requires_human_intervention")):
                self._last_cycle_clean = False
                self._last_cycle_deadline = False
                self.telemetry.record_human_intervention()
                self.memory.append(
                    "human_intervention_required",
                    {
                        "cycle_id": cycle_id,
                        "goal": self.goal,
                        "status": "stopped",
                        "message": "Planner requested human intervention; autonomous execution halted.",
                    },
                )
                self.memory.append(
                    "cycle_summary",
                    {
                        "cycle_id": cycle_id,
                        "goal": self.goal,
                        "clean": False,
                        "deadline_stopped": False,
                        "human_intervention_required": True,
                    },
                )
                self.latest_results = [
                    {
                        "task_id": "human_intervention_required",
                        "status": "skipped",
                        "reason": "planner_requested_human_intervention",
                        "result": {"status": "success", "note": "No autonomous execution due to required human intervention."},
                        "review": {"status": "pass", "summary": "Human intervention requested; autonomous changes withheld safely."},
                    }
                ]
                _loop_log.warning("Planner requested human intervention; stopping autonomous cycle.")
                return not bool(getattr(self, "_fixed_goal_only", False))
            _log_debug_event("[PLAN CREATED]", {"cycle_id": cycle_id, "plan": plan})
            tasks = self.planner.decompose(plan)
            for i, t in enumerate(tasks):
                t["_plan_order"] = i
            self.memory.append("plan", {"cycle_id": cycle_id, "goal": self.goal, "plan": plan})

            if self._should_abort_cycle():
                deadline_stopped = True
                cycle_dirty = True
                self.memory.append(
                    "deadline",
                    {"cycle_id": cycle_id, "phase": "before_tasks", "goal": self.goal},
                )
                self._last_cycle_deadline = True
                self._last_cycle_clean = False
                learning_update = self.memory.update_learning()
                _log_debug_event("[LEARNING UPDATE]", learning_update)
                self.memory.append(
                    "cycle_summary",
                    {
                        "cycle_id": cycle_id,
                        "goal": self.goal,
                        "clean": False,
                        "deadline_stopped": True,
                    },
                )
                return True

            cycle_dirty_box = [cycle_dirty]
            waves = tasks_to_waves(tasks)
            executed_count = 0
            task_cap = _effective_tasks_per_cycle_cap()
            for wave in waves:
                self._wait_while_paused()
                if self._should_abort_cycle():
                    deadline_stopped = True
                    cycle_dirty_box[0] = True
                    self.memory.append(
                        "deadline",
                        {"cycle_id": cycle_id, "phase": "mid_cycle", "goal": self.goal},
                    )
                    break

                ready: list[dict[str, Any]] = []
                for task in wave:
                    if task_cap and executed_count >= task_cap:
                        task["status"] = "skipped_cap"
                        self.memory.append(
                            "task_skipped",
                            {"reason": "max_tasks_per_cycle", "task_id": task.get("id"), "cycle_id": cycle_id},
                        )
                        continue
                    from core.stability.task_priority import should_run_priority

                    if not should_run_priority(self._task_stability_priority(task)):
                        task["status"] = "skipped_load"
                        self.memory.append(
                            "task_skipped",
                            {"reason": "load_policy", "tier": task.get("tier"), "task_id": task.get("id")},
                        )
                        continue
                    ready.append(task)

                if not ready:
                    continue

                use_parallel = (
                    effective_parallel_shell_enabled()
                    and len(ready) > 1
                    and wave_eligible_for_parallel_shell(ready)
                )
                if use_parallel:
                    try:
                        from core.stability.resource_monitor import is_overloaded

                        if is_overloaded():
                            use_parallel = False
                    except (ImportError, OSError, ValueError, RuntimeError):
                        use_parallel = False

                if use_parallel:
                    batch: list[dict[str, Any]] = []
                    for task in ready:
                        if task_cap and executed_count >= task_cap:
                            break
                        tid = f"{cycle_id}-{task.get('_plan_order', 0)}"
                        br = self._approval_gate_result(task, cycle_id, tid)
                        if br is not None:
                            from thiramai.runtime import ai_observability

                            ai_observability.record_step()
                            task["status"] = "running"
                            _log_debug_event("[STEP START]", {"task_id": tid, "step": task})
                            br.setdefault(
                                "policy_decision",
                                {
                                    "allow": False,
                                    "policy_id": "approval_gate.blocked",
                                    "reason": str(br.get("error", "approval blocked")),
                                },
                            )
                            self._audit_execution(cycle_id=cycle_id, task_id=tid, task=task, result=br)
                            review = self.reviewer.review(task, br)
                            self._step_record_and_branch(
                                cycle_id, tid, task, br, review, learning_snapshot, cycle_dirty_box
                            )
                            executed_count += 1
                            continue
                        batch.append(task)
                    if batch:
                        from thiramai.runtime import ai_observability

                        results = self.executor.parallel_audit_shell_batch(batch)
                        for task, result in zip(batch, results):
                            if self._should_abort_cycle():
                                deadline_stopped = True
                                cycle_dirty_box[0] = True
                                break
                            executed_count += 1
                            tid = f"{cycle_id}-{task.get('_plan_order', 0)}"
                            ai_observability.record_step()
                            _log_debug_event("[STEP START]", {"task_id": tid, "step": task, "parallel_batch": True})
                            _log_debug_event(
                                "[DECISION MADE]",
                                {
                                    "task_id": tid,
                                    "decision_type": task.get("type"),
                                    "result_status": result.get("status"),
                                },
                            )
                            self._audit_execution(cycle_id=cycle_id, task_id=tid, task=task, result=result)
                            review = self.reviewer.review(task, result)
                            self._step_record_and_branch(
                                cycle_id, tid, task, result, review, learning_snapshot, cycle_dirty_box
                            )
                else:
                    for task in ready:
                        if task_cap and executed_count >= task_cap:
                            break
                        if self._should_abort_cycle():
                            deadline_stopped = True
                            cycle_dirty_box[0] = True
                            break
                        executed_count += 1
                        task["status"] = "running"
                        self._run_single_task_step(cycle_id, task, learning_snapshot, cycle_dirty_box)

            cycle_dirty = cycle_dirty_box[0]

            learning_update = self.memory.update_learning()
            _log_debug_event("[LEARNING UPDATE]", learning_update)
            for pattern in learning_update.get("failures", []):
                _log_debug_event("[PATTERN DETECTED]", pattern)
            self._last_cycle_deadline = deadline_stopped
            cycle_dirty = cycle_dirty or bool(getattr(self, "_cycle_quality_dirty", False))
            self._last_cycle_clean = not cycle_dirty and not deadline_stopped
            self.memory.append(
                "cycle_summary",
                {
                    "cycle_id": cycle_id,
                    "goal": self.goal,
                    "clean": self._last_cycle_clean,
                    "deadline_stopped": deadline_stopped,
                },
            )
            return True

        except Exception as exc:
            self._last_cycle_clean = False
            self._last_cycle_deadline = False
            incident = {"cycle_id": cycle_id, "error": str(exc)}
            self.failures.append(incident)
            self.memory.append("failure", incident)
            logging.exception("Cycle failed: %s", exc)
            try:
                from thiramai.runtime import ai_observability

                ai_observability.record_failure(str(exc), extra={"cycle_id": cycle_id})
            except Exception:
                pass
            _telemetry.error("autonomous_cycle_failed cycle_id=%s err=%s", cycle_id, exc)
            try:
                healer = SelfHealer(executor=self.executor)
                heal_outcome = healer.heal_from_exception(exc, traceback.format_exc())
                self.memory.append(
                    "self_heal",
                    {"cycle_id": cycle_id, "outcome": heal_outcome},
                )
            except Exception as heal_exc:
                logging.exception("Self-healing failed: %s", heal_exc)
            return False
        finally:
            elapsed = time.monotonic() - cycle_started_at
            self.telemetry.record_cycle_time(elapsed)
            if not self.stop_event.is_set():
                self.telemetry.set_runtime_status(goal=self.goal, cycle_id=cycle_id, task="idle")

    def run_forever(self, max_iterations: int | None = None, *, dashboard: bool = False) -> None:
        cap = THIRAMAI_MAX_LOOP_ITERATIONS if max_iterations is None else max(0, int(max_iterations))
        hard = int(THIRAMAI_FOREVER_HARD_CAP_ITERATIONS or 0)
        if hard > 0:
            if cap <= 0:
                cap = hard
            else:
                cap = min(cap, hard)
        iteration = 0
        consecutive_failures = 0
        _loop_log.info(
            "[MODE] effective=%s requested=%s max_iterations=%s fail_safe_after=%s",
            get_thiramai_mode(),
            THIRAMAI_MODE_REQUESTED,
            cap or "unlimited",
            THIRAMAI_MAX_CONSECUTIVE_CYCLE_FAILURES,
        )
        self._log_health_compact()
        live = None
        dashboard_ui = None
        if dashboard:
            try:
                from rich.live import Live
                from thiramai.ui.dashboard import RuntimeDashboard

                dashboard_ui = RuntimeDashboard(self.telemetry)
                live = Live(dashboard_ui.render(), refresh_per_second=4, transient=False)
                live.start()
            except Exception as exc:
                _loop_log.warning("Dashboard disabled (rich unavailable or init failed): %s", exc)
                live = None
                dashboard_ui = None
        wd_sec = int(THIRAMAI_WATCHDOG_MAX_SECONDS or 0)
        if wd_sec > 0:
            def _watchdog() -> None:
                time.sleep(float(wd_sec))
                _loop_log.error("[WATCHDOG] THIRAMAI_WATCHDOG_MAX_SECONDS elapsed; requesting stop.")
                self.request_stop()

            threading.Thread(target=_watchdog, name="thiramai-watchdog", daemon=True).start()
        while True:
            iteration += 1
            _loop_log.info("[LOOP ITERATION] %s cap=%s", iteration, cap or "unlimited")
            if cap and iteration > cap:
                _loop_log.info("[LOOP ITERATION] max_iterations reached; exiting run_forever.")
                break

            cycle_id = int(time.time())
            ok = self._run_autonomous_cycle(cycle_id)
            if THIRAMAI_STOP_FOREVER_ON_CLEAN_CYCLE and ok and getattr(self, "_last_cycle_clean", False):
                _loop_log.info(
                    "[LOOP] THIRAMAI_STOP_FOREVER_ON_CLEAN_CYCLE: clean cycle completed; exiting run_forever."
                )
                break
            if ok:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                _loop_log.warning(
                    "[FAIL SAFE] consecutive_cycle_failures=%s/%s",
                    consecutive_failures,
                    THIRAMAI_MAX_CONSECUTIVE_CYCLE_FAILURES,
                )
                if consecutive_failures >= THIRAMAI_MAX_CONSECUTIVE_CYCLE_FAILURES:
                    _loop_log.error(
                        "[FAIL SAFE TRIGGERED] stopping run_forever after %s consecutive failed cycles.",
                        consecutive_failures,
                    )
                    break

            sleep_seconds = self._compute_sleep_interval()
            _loop_log.info("Cycle complete. Sleeping %s seconds.", sleep_seconds)
            if live is not None and dashboard_ui is not None:
                live.update(dashboard_ui.render())
            time.sleep(sleep_seconds)
        if live is not None:
            live.stop()

    def _execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_type = str(task.get("type", "analysis")).lower()

        if task_type == "device":
            return self._execute_device_action(task)

        agent = self.factory.create_agent(task)
        context = {
            "goal": self.goal,
            "latest_results": self.latest_results[-10:],
            "failures": self.failures[-10:],
        }

        if task_type == "audit":
            return agent.execute(task, self.executor, context)
        if task_type == "coding" or task_type == "fix":
            return agent.execute(task, self.executor, context)
        if task_type == "research":
            return agent.execute(task, context)
        if task_type == "api":
            return agent.execute(task, context)
        return agent.execute(task, context)

    def _execute_replan(self, cycle_id: int, parent_task_id: str, replan: dict[str, Any]) -> None:
        for idx, step in enumerate(self.planner.decompose(replan)):
            step_id = f"{parent_task_id}-r{idx}"
            step["status"] = "running"
            _log_debug_event("[STEP START]", {"task_id": step_id, "step": step})
            result = self._execute_task(step)
            review = self.reviewer.review(step, result)
            step["result_history"].append({"result": result, "review": review})

            record = {
                "cycle_id": cycle_id,
                "task_id": step_id,
                "task": step,
                "result": result,
                "review": review,
                "parent_task_id": parent_task_id,
            }
            self.latest_results.append(record)
            self.memory.append("result", record)
            _log_debug_event("[STEP RESULT]", record)

            if review.get("status") == "pass":
                step["status"] = "success"
            else:
                self._cycle_quality_dirty = True
                step["status"] = "failed"
                self.memory.append(
                    "failure",
                    {
                        "cycle_id": cycle_id,
                        "task_id": step_id,
                        "parent_task_id": parent_task_id,
                        "reason": review.get("reason", "replan step failed"),
                        "failure_type": review.get("failure_type", "invalid_output"),
                        "result": result,
                    },
                )

    def _retry_with_generated_agent(
        self,
        cycle_id: int,
        task_id: str,
        task: dict[str, Any],
        parent_result: dict[str, Any],
        generated_type: str,
    ) -> None:
        retry_task = {**task}
        retry_task["type"] = generated_type
        retry_task["result_history"] = list(task.get("result_history", []))
        retry_task["status"] = "running"

        _log_debug_event(
            "[STEP START]",
            {"task_id": f"{task_id}-g0", "step": retry_task, "source": "generated_agent_retry"},
        )
        result = self._execute_task(retry_task)
        _log_debug_event("[ACTION EXECUTED]", {"task_id": f"{task_id}-g0", "status": result.get("status")})
        review = self.reviewer.review(retry_task, result)
        retry_task["result_history"].append({"result": result, "review": review})

        record = {
            "cycle_id": cycle_id,
            "task_id": f"{task_id}-g0",
            "task": retry_task,
            "result": result,
            "review": review,
            "source": "generated_agent_retry",
            "parent_result": parent_result,
        }
        self.latest_results.append(record)
        self.memory.append("result", record)
        _log_debug_event("[STEP RESULT]", record)

    def _attempt_fix(
        self,
        task: dict[str, Any],
        result: dict[str, Any],
        review: dict[str, str],
        cycle_id: int,
        task_id: str,
    ) -> dict[str, Any]:
        from core.stability.failure_memory import get_failure_memory

        from thiramai.runtime import retry_policy

        attempts: list[dict[str, Any]] = []
        fix_command = review.get("fix", "").strip()
        fm_key = f"{cycle_id}:{task_id}"
        strategy = get_failure_memory().strategy_for("goal_fix", fm_key)
        if retry_policy.should_skip_retries_from_memory(strategy):
            return {
                "cycle_id": cycle_id,
                "task_id": task_id,
                "task": task,
                "initial_result": result,
                "initial_review": review,
                "resolved": False,
                "attempts": attempts,
                "skipped": "failure_memory_skip",
            }

        stderr_hint = str(result.get("stderr") or result.get("error") or "")
        ft = str(review.get("failure_type") or "")
        if retry_policy.is_non_retryable_failure(ft, stderr_hint):
            retry_policy.record_failure_memory_key("goal_fix", fm_key, ft)
            return {
                "cycle_id": cycle_id,
                "task_id": task_id,
                "task": task,
                "initial_result": result,
                "initial_review": review,
                "resolved": False,
                "attempts": attempts,
                "skipped": "non_retryable",
            }

        retry_cap = retry_policy.effective_fix_retry_cap(task.get("retry_limit"))
        for retry in range(retry_cap):
            if not fix_command:
                break
            if retry > 0:
                retry_policy.sleep_backoff(retry - 1)
            task["retries_used"] = int(task.get("retries_used", 0)) + 1
            try:
                fix_result = self.executor.execute_command(
                    fix_command,
                    context=self.executor._build_execution_context(
                        {
                            "type": "fix",
                            "risk_level": task.get("risk_level", "low"),
                            "capabilities": task.get("capabilities", []),
                        }
                    ),
                )
            except (PolicyViolationError, UnsafeCommandError) as exc:
                fix_result = {
                    "status": "blocked",
                    "returncode": -1,
                    "output": "",
                    "error": str(exc),
                    "ok": False,
                    "stdout": "",
                    "stderr": str(exc),
                    "exit_code": -1,
                }
            fix_review = self.reviewer.review(
                {"type": "fix", "command": fix_command, "from_task": task},
                fix_result,
            )
            attempt = {
                "retry": retry + 1,
                "fix_command": fix_command,
                "fix_result": fix_result,
                "fix_review": fix_review,
            }
            attempts.append(attempt)
            task["result_history"].append({"fix_attempt": attempt})
            try:
                from thiramai.runtime import ai_observability

                ai_observability.record_retry(extra={"task_id": task_id, "fix_retry": retry + 1})
            except Exception:
                pass
            if fix_review["status"] == "pass":
                get_failure_memory().reset_key("goal_fix", fm_key)
                return {
                    "cycle_id": cycle_id,
                    "task_id": task_id,
                    "task": task,
                    "initial_result": result,
                    "initial_review": review,
                    "resolved": True,
                    "attempts": attempts,
                }
            fix_command = fix_review.get("fix", "").strip()

        retry_policy.record_failure_memory_key("goal_fix", fm_key, ft or "fix_exhausted")
        return {
            "cycle_id": cycle_id,
            "task_id": task_id,
            "task": task,
            "initial_result": result,
            "initial_review": review,
            "resolved": False,
            "attempts": attempts,
        }

    def _recent_failures_from_memory(self, limit: int = 20) -> list[dict[str, Any]]:
        events = self.memory.read_all()
        failures: list[dict[str, Any]] = []
        for event in reversed(events):
            if event.get("event_type") == "failure":
                payload = event.get("payload", {})
                if isinstance(payload, dict):
                    failures.append(payload)
                if len(failures) >= limit:
                    break
        return list(reversed(failures))

    def _collect_realtime_context(self) -> dict[str, Any]:
        if get_thiramai_mode() != "live":
            ctx = self._minimal_realtime_context()
            _loop_log.info("[MODE] non-live realtime context stub (no external weather/market fetch)")
            return ctx

        weather = get_weather(THIRAMAI_LOCATION)
        market = get_market_prices()
        system_status = get_system_status()
        recent_failures = self._recent_failures_from_memory(limit=5)

        external_data = {
            "weather": weather,
            "market": market,
            "soil_moisture": self._derive_soil_moisture(weather),
        }
        context = {
            "system_status": system_status,
            "external_data": external_data,
            "recent_failures": recent_failures,
        }
        return context

    def _derive_soil_moisture(self, weather: dict[str, Any]) -> float:
        humidity_raw = weather.get("humidity")
        try:
            humidity = float(humidity_raw) / 100.0
        except (TypeError, ValueError):
            humidity = 0.4
        # simple proxy for simulation decisions
        return round(max(0.05, min(humidity * 0.8, 0.95)), 2)

    def _execute_device_action(self, task: dict[str, Any]) -> dict[str, Any]:
        device = str(task.get("device", "irrigation"))
        action = str(task.get("action", "read_sensor"))
        payload = task.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        allowed, reason = self.device_controller.validate_action(device=device, action=action, payload=payload)
        if not allowed:
            return {
                "status": "blocked",
                "returncode": -1,
                "output": "",
                "error": reason,
            }
        result = self.device_controller.send_command(device=device, action=action, payload=payload)
        _log_debug_event("[ACTION EXECUTED]", {"device": device, "action": action, "result": result})
        return result

    def _compute_sleep_interval(self) -> int:
        current = self._collect_realtime_context()
        if self.last_context is None:
            self.last_context = current
            return THIRAMAI_LOOP_SLEEP_SEC

        previous_free = float(self.last_context.get("system_status", {}).get("disk_free_ratio", 0.0))
        current_free = float(current.get("system_status", {}).get("disk_free_ratio", 0.0))
        change = abs(current_free - previous_free)
        failures_now = len(current.get("recent_failures", []))
        self.last_context = current

        if failures_now > 0 or change > THIRAMAI_EVENT_DELTA_THRESHOLD:
            return max(5, int(THIRAMAI_LOOP_SLEEP_SEC / 3))
        return THIRAMAI_LOOP_SLEEP_SEC


def _dashboard_file_path() -> Path:
    return Path(__file__).resolve().parent / "ui" / "dashboard.py"


def _run_doctor() -> int:
    _ensure_runtime_dirs()
    _cli_log.info("Running THIRAMAI doctor checks...")
    issues: list[str] = []
    checks: list[str] = []

    try:
        import docker  # type: ignore

        try:
            docker.from_env().ping()
            checks.append("Docker: OK")
        except Exception as exc:  # noqa: BLE001
            issues.append(f"Docker not reachable: {exc}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"Docker SDK unavailable: {exc}")

    if THIRAMAI_POLICY_MODE not in {"legacy", "hybrid", "strict"}:
        issues.append(f"Invalid THIRAMAI_POLICY_MODE: {THIRAMAI_POLICY_MODE}")
    else:
        checks.append(f"Policy mode: {THIRAMAI_POLICY_MODE}")

    if THIRAMAI_COMMAND_TIMEOUT_SEC < 5:
        issues.append("THIRAMAI_COMMAND_TIMEOUT_SEC is below safe minimum.")
    else:
        checks.append(f"Command timeout: {THIRAMAI_COMMAND_TIMEOUT_SEC}s")

    if THIRAMAI_USE_DOCKER and not THIRAMAI_DOCKER_IMAGE:
        issues.append("THIRAMAI_USE_DOCKER is enabled but THIRAMAI_DOCKER_IMAGE is empty.")
    else:
        checks.append(f"Docker execution: {'enabled' if THIRAMAI_USE_DOCKER else 'disabled'}")

    for line in checks:
        _cli_log.info("[DOCTOR] %s", line)
    for line in issues:
        _cli_log.error("[DOCTOR] %s", line)
    if issues:
        _cli_log.error("Doctor found %s issue(s).", len(issues))
        return 1
    _cli_log.info("Doctor checks passed.")
    return 0


def _launch_streamlit_dashboard() -> int:
    _ensure_runtime_dirs()
    dashboard_path = _dashboard_file_path()
    cmd = [sys.executable, "-m", "streamlit", "run", str(dashboard_path)]
    _cli_log.info("Launching dashboard: %s", " ".join(cmd))
    try:
        return subprocess.call(cmd)
    except Exception as exc:  # noqa: BLE001
        _cli_log.exception("Failed to launch Streamlit dashboard: %s", exc)
        return 1


def cli_entrypoint(argv: list[str] | None = None) -> int:
    _ensure_runtime_dirs()
    parser = argparse.ArgumentParser(prog="thiramai", description="THIRAMAI production CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Execute THIRAMAI autonomous loop.")
    run_parser.add_argument("goal", nargs="?", default=THIRAMAI_GOAL, help='Goal text, e.g. "Audit and optimize jaggery plan".')
    run_parser.add_argument("--max-iterations", type=int, default=None, help="Optional loop iteration cap.")
    run_parser.add_argument("--dashboard", action="store_true", help="Enable Rich terminal dashboard.")

    subparsers.add_parser("dashboard", help="Launch Streamlit dashboard.")
    subparsers.add_parser("doctor", help="Validate runtime dependencies and configuration.")

    args = parser.parse_args(argv)

    if args.command == "run":
        _cli_log.info("Starting THIRAMAI run command.")
        engine = JarvisCore(goal=str(args.goal))
        engine.run_forever(max_iterations=args.max_iterations, dashboard=bool(args.dashboard))
        return 0
    if args.command == "dashboard":
        return _launch_streamlit_dashboard()
    if args.command == "doctor":
        return _run_doctor()
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(cli_entrypoint())
