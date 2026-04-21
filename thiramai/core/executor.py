import shlex
import subprocess
import time
import os
import logging
from pathlib import Path
from typing import Any, List

from thiramai.config import (
    ALLOWED_COMMANDS,
    BLOCKED_TOKENS,
    THIRAMAI_DOCKER_IMAGE,
    THIRAMAI_DOCKER_NETWORK_ENABLED,
    THIRAMAI_USE_DOCKER,
    THIRAMAI_POLICY_MODE,
    THIRAMAI_COMMAND_TIMEOUT_SEC,
    THIRAMAI_MAX_FIX_RETRIES,
    effective_parallel_shell_enabled,
    get_thiramai_mode,
)
from thiramai.policy.engine import PolicyEngine
from thiramai.policy.models import ExecutionContext

_exec_log = logging.getLogger("thiramai.executor")


class UnsafeCommandError(Exception):
    pass


class PolicyViolationError(Exception):
    def __init__(self, policy_id: str, reason: str) -> None:
        super().__init__(f"{policy_id}: {reason}")
        self.policy_id = policy_id
        self.reason = reason


def classify_failure(result: dict[str, Any]) -> str:
    """
    Classify execution outcome for autonomy policy.

    ``temporary``: retry/backoff may help (timeout, flake).
    ``critical``: blocked or invariant violation.
    ``recoverable``: command ran but unsuccessful (non-zero).
    """
    status = str(result.get("status", "")).lower()
    if status == "timeout":
        return "temporary"
    if status == "blocked":
        return "critical"
    if status == "error":
        return "recoverable"
    if status == "success":
        return "success"
    return "recoverable"


class Executor:
    SAFE_COMMANDS = {"ls", "pwd", "whoami", "echo", "dir", "python", "pip"}
    CONTROLLED_COMMANDS = {"docker", "git", "docker-compose"}
    DANGEROUS_FLAGS = {"--force", "-rf", "-fd", "-fdx"}
    SAFE_CAPABILITIES = {"search_tool", "knowledge_retrieval", "read_fs", "run_tests", "git_read", "lint"}
    HITL_APPROVE_FILE = "approve.flag"
    HITL_REJECT_FILE = "reject.flag"

    def __init__(self) -> None:
        self.policy_engine = PolicyEngine(allow_high_risk=False)
        self._last_policy_decision: dict[str, Any] = {"allow": None, "policy_id": "not_evaluated", "reason": ""}
        self._hitl_dir = Path.cwd() / "runtime" / "hitl"

    def _validate_blocked_tokens(self, parts: List[str]) -> None:
        normalized = [p.lower() for p in parts]
        for blocked in BLOCKED_TOKENS:
            blocked_parts = shlex.split(blocked.lower())
            if len(blocked_parts) == 1:
                if blocked_parts[0] in normalized:
                    raise UnsafeCommandError(f"Blocked token detected: {blocked}")
                continue

            window_size = len(blocked_parts)
            max_idx = len(normalized) - window_size + 1
            for idx in range(max_idx):
                if normalized[idx : idx + window_size] == blocked_parts:
                    raise UnsafeCommandError(f"Blocked token detected: {blocked}")

    def _validate_arguments(self, parts: List[str]) -> None:
        base = parts[0].lower()
        args = [arg.lower() for arg in parts[1:]]

        for arg in args:
            if arg in self.DANGEROUS_FLAGS:
                raise UnsafeCommandError(f"Dangerous flag blocked: {arg}")

            # Common recursive/wildcard wipe patterns.
            if arg in {"/", "\\", "/*", "\\*", "../", "..\\", "~", "~/*", "~\\*"}:
                raise UnsafeCommandError(f"Dangerous recursive delete pattern blocked: {arg}")

        if base == "git":
            if args and args[0] == "clean":
                blocked_clean_flags = {"-fdx", "-xdf", "-fd", "-df", "-fx", "-xf"}
                if any(flag in blocked_clean_flags for flag in args[1:]):
                    raise UnsafeCommandError("Blocked dangerous git cleanup command.")

        if base in {"docker", "docker-compose"}:
            if len(args) >= 2 and args[0] == "system" and args[1] == "prune":
                raise UnsafeCommandError("Blocked dangerous docker system prune command.")
            if args and args[0] == "rm" and any(flag in {"-f", "--force"} for flag in args[1:]):
                raise UnsafeCommandError("Blocked dangerous forced docker remove command.")

    def _build_execution_context(self, task: dict[str, Any] | None = None) -> ExecutionContext:
        data = task if isinstance(task, dict) else {}
        tenant_raw = data.get("tenant_id")
        tenant_id: int | None = None
        allowed_task_types = {"audit", "analysis", "coding", "research", "fix", "api", "device"}
        allowed_risk_levels = {"low", "medium", "high"}
        if tenant_raw is not None:
            try:
                tenant_id = int(tenant_raw)
            except (TypeError, ValueError):
                tenant_id = None
        task_type = str(data.get("type", "analysis")).lower()
        if task_type not in allowed_task_types:
            task_type = "analysis"
        risk_level = str(data.get("risk_level", "low")).lower()
        if risk_level not in allowed_risk_levels:
            risk_level = "low"
        return ExecutionContext(
            tenant_id=tenant_id,
            task_type=task_type,
            risk_level=risk_level,
            capabilities=[
                str(x).strip().lower()
                for x in data.get("capabilities", [])
                if str(x).strip().lower() in self.SAFE_CAPABILITIES
            ],
        )

    def _validate_command(self, command: str, *, context: ExecutionContext | None = None) -> List[str]:
        self._last_policy_decision = {"allow": None, "policy_id": "not_evaluated", "reason": ""}
        text = command.strip()
        if not text:
            raise UnsafeCommandError("Empty command.")

        try:
            parts = shlex.split(text)
        except ValueError as exc:
            raise UnsafeCommandError(f"Command parse error: {exc}") from exc

        if not parts:
            raise UnsafeCommandError("Unable to parse command.")

        if THIRAMAI_POLICY_MODE in {"legacy", "hybrid"}:
            self._validate_blocked_tokens(parts)
            base = parts[0].lower()
            if base not in ALLOWED_COMMANDS:
                raise UnsafeCommandError(f"Command not in allowlist: {base}")
            if base not in self.SAFE_COMMANDS and base not in self.CONTROLLED_COMMANDS:
                raise UnsafeCommandError(f"Command category not permitted: {base}")
            self._validate_arguments(parts)

        if THIRAMAI_POLICY_MODE in {"hybrid", "strict"}:
            decision = self.policy_engine.evaluate(parts, context or ExecutionContext())
            self._last_policy_decision = {
                "allow": bool(decision.allow),
                "policy_id": str(decision.policy_id),
                "reason": str(decision.reason),
            }
            if not decision.allow:
                _exec_log.warning(
                    "[POLICY DENY] policy_id=%s reason=%s",
                    decision.policy_id,
                    decision.reason,
                )
                raise PolicyViolationError(decision.policy_id, decision.reason)
        else:
            self._last_policy_decision = {"allow": True, "policy_id": "legacy.v1.allow", "reason": "Legacy validation passed."}
        return parts

    def _wait_for_hitl_approval(self, *, context: ExecutionContext | None, command: str) -> dict[str, Any] | None:
        ctx = context or ExecutionContext()
        if str(ctx.risk_level).lower() != "high":
            return None
        self._hitl_dir.mkdir(parents=True, exist_ok=True)
        approve_path = self._hitl_dir / self.HITL_APPROVE_FILE
        reject_path = self._hitl_dir / self.HITL_REJECT_FILE
        timeout_sec = max(10, int(os.getenv("THIRAMAI_HITL_TIMEOUT_SEC", "600")))
        poll_sec = max(1.0, float(os.getenv("THIRAMAI_HITL_POLL_SEC", "2")))
        started = time.time()
        _exec_log.info("[HITL] high-risk command pending approval command=%s", command)
        while (time.time() - started) < timeout_sec:
            if reject_path.exists():
                try:
                    reject_path.unlink()
                except OSError:
                    pass
                return {
                    "status": "blocked",
                    "returncode": -1,
                    "output": "",
                    "error": "HITL rejected high-risk command.",
                    "command": command,
                    "ok": False,
                    "stdout": "",
                    "stderr": "HITL rejected high-risk command.",
                    "exit_code": -1,
                    "policy_decision": {
                        "allow": False,
                        "policy_id": "hitl.v1.rejected",
                        "reason": "Operator rejected high-risk command.",
                    },
                }
            if approve_path.exists():
                try:
                    approve_path.unlink()
                except OSError:
                    pass
                _exec_log.info("[HITL] approval received")
                return None
            time.sleep(poll_sec)
        return {
            "status": "blocked",
            "returncode": -1,
            "output": "",
            "error": "HITL approval timed out for high-risk command.",
            "command": command,
            "ok": False,
            "stdout": "",
            "stderr": "HITL approval timed out for high-risk command.",
            "exit_code": -1,
            "policy_decision": {
                "allow": False,
                "policy_id": "hitl.v1.timeout",
                "reason": "No human approval received within timeout.",
            },
        }

    def _validate_container_paths(self, parts: List[str]) -> None:
        for token in parts[1:]:
            tok = str(token).strip()
            if not tok or tok.startswith("-"):
                continue
            normalized = tok.replace("\\", "/")
            if ".." in normalized:
                raise UnsafeCommandError("Path traversal token detected (`..`) for container command.")
            if normalized.startswith("/") and not (
                normalized.startswith("/workspace") or normalized.startswith("/tmp/thiramai_scratch")
            ):
                raise UnsafeCommandError(
                    "Absolute paths outside /workspace or /tmp/thiramai_scratch are blocked in container mode."
                )

    def _execute_in_docker(self, parts: List[str], command: str, *, context: ExecutionContext | None = None) -> dict[str, Any]:
        try:
            import docker
            from docker.errors import DockerException
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Docker SDK not available: {exc}") from exc

        try:
            self._validate_container_paths(parts)
            client = docker.from_env()
            workspace = Path.cwd().resolve()
            task_type = str((context or ExecutionContext()).task_type).lower()
            workspace_mode = "rw" if task_type in {"coding", "fix"} else "ro"
            volume_binding = {str(workspace): {"bind": "/workspace", "mode": workspace_mode}}
            out = client.containers.run(
                image=THIRAMAI_DOCKER_IMAGE,
                command=parts,
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
                working_dir="/workspace",
                user="thiramai_runner",
                volumes=volume_binding,
                nano_cpus=500_000_000,  # 0.5 cores
                mem_limit="512m",
                network_disabled=not THIRAMAI_DOCKER_NETWORK_ENABLED,
                tmpfs={"/tmp/thiramai_scratch": "rw,nosuid,nodev,noexec,size=64m"},
            )
            text = out.decode("utf-8", errors="replace").strip() if isinstance(out, (bytes, bytearray)) else str(out).strip()
            return {
                "status": "success",
                "returncode": 0,
                "output": text,
                "error": "",
                "command": command,
                "command_parts": parts,
                "ok": True,
                "stdout": text,
                "stderr": "",
                "exit_code": 0,
                "policy_decision": dict(self._last_policy_decision),
                "execution_backend": "docker",
                "workspace_mode": workspace_mode,
                "scratch_dir": "/tmp/thiramai_scratch",
            }
        except docker.errors.ContainerError as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace").strip() if exc.stdout else ""
            stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
            return {
                "status": "error",
                "returncode": int(exc.exit_status),
                "output": stdout,
                "error": stderr or str(exc),
                "command": command,
                "command_parts": parts,
                "ok": False,
                "stdout": stdout,
                "stderr": stderr or str(exc),
                "exit_code": int(exc.exit_status),
                "policy_decision": dict(self._last_policy_decision),
                "execution_backend": "docker",
                "scratch_dir": "/tmp/thiramai_scratch",
            }
        except DockerException as exc:
            raise RuntimeError(f"Docker execution failed: {exc}") from exc

    def execute_command(self, command: str, *, context: ExecutionContext | None = None) -> dict[str, Any]:
        try:
            if get_thiramai_mode() == "dry-run":
                _exec_log.info("[SAFE EXECUTION] command=%s status=skipped(dry-run)", command)
                return {
                    "status": "success",
                    "returncode": 0,
                    "output": "THIRAMAI_DRY_RUN (executor skipped)",
                    "error": "",
                    "command": command,
                    "command_parts": [],
                    "ok": True,
                    "stdout": "THIRAMAI_DRY_RUN (executor skipped)",
                    "stderr": "",
                    "exit_code": 0,
                    "policy_decision": {"allow": True, "policy_id": "dry_run.skip", "reason": "Execution skipped in dry-run mode."},
                }
            parts = self._validate_command(command, context=context)
            hitl_result = self._wait_for_hitl_approval(context=context, command=command)
            if hitl_result is not None:
                _exec_log.info("[SAFE EXECUTION] command=%s status=blocked(HITL)", command)
                return hitl_result
            _exec_log.debug("[SAFE EXECUTION] command=%s parts=%s", command, parts)
            if THIRAMAI_USE_DOCKER:
                return self._execute_in_docker(parts, command, context=context)
            proc = subprocess.run(
                parts,
                shell=False,
                text=True,
                capture_output=True,
                timeout=THIRAMAI_COMMAND_TIMEOUT_SEC,
            )
            status = "success" if proc.returncode == 0 else "error"
            _exec_log.info("[SAFE EXECUTION] command=%s status=%s", command, status)
            return {
                "status": status,
                "returncode": proc.returncode,
                "output": proc.stdout.strip(),
                "error": proc.stderr.strip(),
                "command": command,
                "command_parts": parts,
                "ok": proc.returncode == 0,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "exit_code": proc.returncode,
                "policy_decision": dict(self._last_policy_decision),
                "execution_backend": "host",
            }
        except UnsafeCommandError as exc:
            policy_decision = (
                dict(self._last_policy_decision)
                if self._last_policy_decision.get("allow") is not None
                else {"allow": False, "policy_id": "legacy.v1.blocked", "reason": str(exc)}
            )
            _exec_log.info("[SAFE EXECUTION] command=%s status=blocked", command)
            return {
                "status": "blocked",
                "returncode": -1,
                "output": "",
                "error": str(exc),
                "command": command,
                "ok": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "policy_decision": policy_decision,
            }
        except subprocess.TimeoutExpired:
            _exec_log.warning("[SAFE EXECUTION] command=%s status=timeout", command)
            message = f"Command timed out after {THIRAMAI_COMMAND_TIMEOUT_SEC} seconds."
            return {
                "status": "timeout",
                "returncode": 124,
                "output": "",
                "error": message,
                "command": command,
                "ok": False,
                "stdout": "",
                "stderr": message,
                "exit_code": 124,
                "policy_decision": dict(self._last_policy_decision),
            }
        except Exception as exc:
            if isinstance(exc, PolicyViolationError):
                raise
            _exec_log.exception("[SAFE EXECUTION] command=%s status=error err=%s", command, exc)
            return {
                "status": "error",
                "returncode": -1,
                "output": "",
                "error": str(exc),
                "command": command,
                "ok": False,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
            }

    def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        command = str(task.get("command", "")).strip()
        if not command:
            message = "Task is missing 'command'."
            return {
                "status": "blocked",
                "returncode": -1,
                "output": "",
                "error": message,
                "ok": False,
                "stdout": "",
                "stderr": message,
                "exit_code": -1,
            }
        context = self._build_execution_context(task)
        return self.execute_command(command, context=context)

    def execute_task_with_retries(
        self,
        task: dict[str, Any],
        *,
        exec_once: Any | None = None,
    ) -> dict[str, Any]:
        """
        Run shell task up to retry_limit with bounded backoff on temporary failures.

        *exec_once* optional callable(task)->dict overrides default execute(task).
        """
        run = exec_once if callable(exec_once) else self.execute
        attempts: list[dict[str, Any]] = []
        limit = max(0, min(int(task.get("retry_limit", THIRAMAI_MAX_FIX_RETRIES)), 5))
        tries = limit + 1
        last: dict[str, Any] = {}
        for i in range(tries):
            last = run(task)
            attempts.append({"attempt": i + 1, "result": last})
            cls = classify_failure(last)
            task["retries_used"] = i
            if cls in {"success"} or last.get("ok"):
                return {**last, "_attempts": attempts, "_failure_class": cls}
            if cls == "critical":
                return {**last, "_attempts": attempts, "_failure_class": cls}
            if i + 1 >= tries:
                break
            # light backoff for temporary / recoverable
            delay = min(8.0, 0.5 * (2**i))
            time.sleep(delay)
        return {**last, "_attempts": attempts, "_failure_class": classify_failure(last)}

    def parallel_audit_shell_batch(self, tasks: list[dict[str, Any]], *, max_workers: int = 3) -> list[dict[str, Any]]:
        """
        Run multiple independent audit shell tasks concurrently when enabled and host not overloaded.
        Falls back to sequential execution when disabled, overloaded, or single task.
        """
        if not tasks:
            return []
        if not effective_parallel_shell_enabled() or len(tasks) == 1:
            return [self.execute_task_with_retries(t) for t in tasks]

        try:
            from core.stability.resource_monitor import increment_tracked_tasks, is_overloaded
        except ImportError:
            return [self.execute_task_with_retries(t) for t in tasks]

        if is_overloaded():
            return [self.execute_task_with_retries(t) for t in tasks]

        from thiramai.runtime.light_queue import LightQueue

        workers = max(1, min(int(max_workers), len(tasks), 6))
        pool = LightQueue(max_workers=workers)
        timeout_sec = max(float(THIRAMAI_COMMAND_TIMEOUT_SEC) * 4.0, 60.0)
        futs: list = []
        try:
            for _t in tasks:
                increment_tracked_tasks(1)
                futs.append(pool.submit(self.execute_task_with_retries, _t))
            out: list[dict[str, Any]] = []
            for fut in futs:
                try:
                    out.append(fut.result(timeout=timeout_sec))
                except Exception as exc:  # noqa: BLE001
                    out.append(
                        {
                            "status": "error",
                            "returncode": -1,
                            "output": "",
                            "error": str(exc),
                            "ok": False,
                            "stdout": "",
                            "stderr": str(exc),
                            "exit_code": -1,
                        }
                    )
                finally:
                    increment_tracked_tasks(-1)
            return out
        except Exception:
            for fut in futs:
                if hasattr(fut, "cancel") and not fut.done():
                    fut.cancel()
            raise
