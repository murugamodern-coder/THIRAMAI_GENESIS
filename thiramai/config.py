import os
import subprocess
from pathlib import Path
import logging

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MEMORY_FILE = DATA_DIR / "memory.json"
ENV_PATH = BASE_DIR.parent / ".env"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("thiramai.config")

load_dotenv(dotenv_path=ENV_PATH, override=False)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
THIRAMAI_GOAL = os.getenv("THIRAMAI_GOAL", "Audit my system and fix issues").strip()
# 1 = sovereign dynamic goal selection each cycle (seeded by THIRAMAI_GOAL). 0 = fixed THIRAMAI_GOAL only.
THIRAMAI_DYNAMIC_GOALS = os.getenv("THIRAMAI_DYNAMIC_GOALS", "1").strip().lower() in {"1", "true", "yes", "on"}
THIRAMAI_LOOP_SLEEP_SEC = max(5, int(os.getenv("THIRAMAI_LOOP_SLEEP_SEC", "30")))
THIRAMAI_COMMAND_TIMEOUT_SEC = max(5, int(os.getenv("THIRAMAI_COMMAND_TIMEOUT_SEC", "30")))
THIRAMAI_USE_DOCKER = os.getenv("THIRAMAI_USE_DOCKER", "0").strip().lower() in {"1", "true", "yes", "on"}
THIRAMAI_DOCKER_IMAGE = os.getenv("THIRAMAI_DOCKER_IMAGE", "thiramai-runner:latest").strip()
THIRAMAI_DOCKER_NETWORK_ENABLED = os.getenv("THIRAMAI_DOCKER_NETWORK_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
THIRAMAI_MAX_FIX_RETRIES = max(1, int(os.getenv("THIRAMAI_MAX_FIX_RETRIES", "2")))
# Loop guard: 0 = unlimited (legacy forever loop).
THIRAMAI_MAX_LOOP_ITERATIONS = max(0, int(os.getenv("THIRAMAI_MAX_LOOP_ITERATIONS", "0")))
THIRAMAI_MAX_CONSECUTIVE_CYCLE_FAILURES = max(1, int(os.getenv("THIRAMAI_MAX_CONSECUTIVE_CYCLE_FAILURES", "5")))
# API / pipeline: wall-clock budget for one goal execution (seconds).
THIRAMAI_GOAL_MAX_SECONDS = max(30, int(os.getenv("THIRAMAI_GOAL_MAX_SECONDS", "300")))
# When 1, ``run_forever`` exits after the first cycle where every step passes review (no failures/deadline abort).
THIRAMAI_STOP_FOREVER_ON_CLEAN_CYCLE = (
    os.getenv("THIRAMAI_STOP_FOREVER_ON_CLEAN_CYCLE", "0").strip().lower() in {"1", "true", "yes", "on"}
)
# Optional file path: if this file exists, autonomous cycles abort between steps (emergency stop).
THIRAMAI_EMERGENCY_STOP_FILE = os.getenv("THIRAMAI_EMERGENCY_STOP_FILE", "").strip()
# Safe parallel shell execution for independent audit steps (uses LightQueue + resource monitor).
THIRAMAI_PARALLEL_SHELL_ENABLED = (
    os.getenv("THIRAMAI_PARALLEL_SHELL_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
)
# Command governance policy mode:
# - legacy: token/allowlist checks only
# - hybrid: legacy checks + policy engine evaluation
# - strict: policy engine evaluation only
_policy_mode_raw = os.getenv("THIRAMAI_POLICY_MODE", "hybrid").strip().lower()
THIRAMAI_POLICY_MODE = _policy_mode_raw if _policy_mode_raw in {"legacy", "hybrid", "strict"} else "hybrid"
# Reviewer: below this confidence a passing step is treated as fail (triggers retry/replan).
THIRAMAI_REVIEW_MIN_CONFIDENCE = max(0.0, min(1.0, float(os.getenv("THIRAMAI_REVIEW_MIN_CONFIDENCE", "0.45") or "0.45")))
# Second LLM verification pass when primary confidence is borderline.
THIRAMAI_REVIEW_DOUBLE_CHECK = (
    os.getenv("THIRAMAI_REVIEW_DOUBLE_CHECK", "1").strip().lower() in {"1", "true", "yes", "on"}
)
# Block on task risk_level=high until POST /ai/approve (seconds; large default for batch ops).
THIRAMAI_APPROVAL_TIMEOUT_SEC = max(30.0, float(os.getenv("THIRAMAI_APPROVAL_TIMEOUT_SEC", "3600") or "3600"))
# Hard cap on steps per autonomous cycle (0 = unlimited).
THIRAMAI_MAX_TASKS_PER_CYCLE = max(0, int(os.getenv("THIRAMAI_MAX_TASKS_PER_CYCLE", "0") or "0"))
# Persist goal API jobs to SQLite (restart-safe). THIRAMAI_JOB_SQLITE_ENABLED wins when set (0/1).
_job_sqlite_alias = (os.getenv("THIRAMAI_JOB_SQLITE_ENABLED") or "").strip().lower()
if _job_sqlite_alias in ("0", "false", "no", "off"):
    THIRAMAI_JOB_SQLITE = False
elif _job_sqlite_alias in ("1", "true", "yes", "on"):
    THIRAMAI_JOB_SQLITE = True
else:
    THIRAMAI_JOB_SQLITE = os.getenv("THIRAMAI_JOB_SQLITE", "1").strip().lower() in {"1", "true", "yes", "on"}
# On server start: mark running/queued jobs as interrupted (vs re-queue).
THIRAMAI_JOB_RECOVER_INTERRUPTED = (
    os.getenv("THIRAMAI_JOB_RECOVER_INTERRUPTED", "1").strip().lower() in {"1", "true", "yes", "on"}
)
THIRAMAI_JOB_RESUME_QUEUED = os.getenv("THIRAMAI_JOB_RESUME_QUEUED", "0").strip().lower() in {"1", "true", "yes", "on"}
# When 1, POST /ai/goal only enqueues SQLite rows with dispatch_mode=worker (run ``python -m thiramai.worker``).
THIRAMAI_GOAL_WORKER_DISPATCH = os.getenv("THIRAMAI_GOAL_WORKER_DISPATCH", "0").strip().lower() in {"1", "true", "yes", "on"}
# Worker process gate (``python -m thiramai.worker`` requires THIRAMAI_WORKER_MODE=1).
THIRAMAI_WORKER_MODE = os.getenv("THIRAMAI_WORKER_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}
# Idle poll interval when no queued worker jobs (seconds).
THIRAMAI_WORKER_POLL_SEC = max(0.2, float(os.getenv("THIRAMAI_WORKER_POLL_SEC", "2") or "2"))
# Estimated LLM tokens per minute (0 = unlimited). Applied to thiramai.integrations.llm_clients call paths.
THIRAMAI_LLM_TOKEN_BUDGET_PER_MINUTE = max(0, int(os.getenv("THIRAMAI_LLM_TOKEN_BUDGET_PER_MINUTE", "0") or "0"))
# Hard ceiling on run_forever iterations (0 = use THIRAMAI_MAX_LOOP_ITERATIONS only).
THIRAMAI_FOREVER_HARD_CAP_ITERATIONS = max(0, int(os.getenv("THIRAMAI_FOREVER_HARD_CAP_ITERATIONS", "0") or "0"))
# Watchdog: wall-clock seconds after which JarvisCore.run_forever requests stop (0 = off).
THIRAMAI_WATCHDOG_MAX_SECONDS = max(0, int(os.getenv("THIRAMAI_WATCHDOG_MAX_SECONDS", "0") or "0"))
# Emit JSON log lines for thiramai.* loggers (timestamp, level, message parsed as object when possible).
THIRAMAI_STRUCTURED_LOGS = os.getenv("THIRAMAI_STRUCTURED_LOGS", "0").strip().lower() in {"1", "true", "yes", "on"}
# Connector HTTP: require THIRAMAI_CONNECTOR_HTTP_HOSTS non-empty for external GET (localhost always ok).
THIRAMAI_CONNECTOR_HTTP_STRICT = os.getenv("THIRAMAI_CONNECTOR_HTTP_STRICT", "0").strip().lower() in {"1", "true", "yes", "on"}
# Max read/write bytes for connector file ops (cap).
THIRAMAI_CONNECTOR_MAX_FILE_BYTES = max(1024, int(os.getenv("THIRAMAI_CONNECTOR_MAX_FILE_BYTES", "2000000") or "2000000"))

# Conservative operator mode: sequential steps, strict connectors, capped concurrency (phase 60).
THIRAMAI_SAFE_MODE = os.getenv("THIRAMAI_SAFE_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}

_raw_max_concurrent_goal_jobs = max(1, int(os.getenv("THIRAMAI_MAX_CONCURRENT_GOAL_JOBS", "4") or "4"))
# Goals API: max concurrent running goal executions (inline ThreadPool).
THIRAMAI_MAX_CONCURRENT_GOAL_JOBS = (
    min(_raw_max_concurrent_goal_jobs, 2) if THIRAMAI_SAFE_MODE else _raw_max_concurrent_goal_jobs
)
# Per autonomous cycle cap when set (>0); combines with THIRAMAI_MAX_TASKS_PER_CYCLE (minimum applied).
THIRAMAI_MAX_TASKS_PER_JOB = max(0, int(os.getenv("THIRAMAI_MAX_TASKS_PER_JOB", "0") or "0"))
# Reject POST /ai/goal when resource_monitor reports overloaded (optional).
# Daily soft quotas per authenticated user (UTC day, SQLite counters). 0 = unlimited.
THIRAMAI_DAILY_GOAL_JOBS_PER_USER = max(0, int(os.getenv("THIRAMAI_DAILY_GOAL_JOBS_PER_USER", "0") or "0"))
THIRAMAI_DAILY_TOKEN_BUDGET_PER_USER = max(
    0, int(os.getenv("THIRAMAI_DAILY_TOKEN_BUDGET_PER_USER", "0") or "0")
)
# Periodic SQLite backup for goal_jobs.sqlite (seconds; 0 = off).
THIRAMAI_SQLITE_BACKUP_INTERVAL_SEC = max(0, int(os.getenv("THIRAMAI_SQLITE_BACKUP_INTERVAL_SEC", "0") or "0"))
THIRAMAI_GOAL_REJECT_ON_OVERLOAD = os.getenv("THIRAMAI_GOAL_REJECT_ON_OVERLOAD", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Goal result cache (POST /ai/goal): skip new work when same goal was completed recently.
THIRAMAI_GOAL_CACHE_ENABLED = os.getenv("THIRAMAI_GOAL_CACHE", "1").strip().lower() in {"1", "true", "yes", "on"}
THIRAMAI_GOAL_CACHE_TTL_SEC = max(30, int(os.getenv("THIRAMAI_GOAL_CACHE_TTL_SEC", "600") or "600"))
# Bump to invalidate in-process goal→result cache without deploy (operator-controlled).
THIRAMAI_GOAL_CACHE_DATA_VERSION = max(1, int(os.getenv("THIRAMAI_GOAL_CACHE_DATA_VERSION", "1") or "1"))

# Worker queue: round-robin across organization_id so one tenant cannot starve others (global workers).
THIRAMAI_GOAL_FAIR_QUEUE_RR = os.getenv("THIRAMAI_GOAL_FAIR_QUEUE_RR", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Mark / alert when job wall time exceeds this (ms). 0 = disabled.
THIRAMAI_GOAL_SLOW_JOB_MS = max(0, int(os.getenv("THIRAMAI_GOAL_SLOW_JOB_MS", "0") or "0"))

# When live LLM calls exhaust retries, return a degraded stub instead of raising (keeps jobs alive).
THIRAMAI_LLM_GRACEFUL_DEGRADE = os.getenv("THIRAMAI_LLM_GRACEFUL_DEGRADE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def resolve_thiramai_version_id() -> str:
    """Git SHA from env, or ``git rev-parse``, else static fallback."""
    for name in ("THIRAMAI_VERSION_ID", "GIT_SHA", "RENDER_GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA"):
        v = (os.getenv(name) or "").strip()
        if v:
            return v[:64]
    try:
        root = ENV_PATH.parent
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if cp.returncode == 0 and (cp.stdout or "").strip():
            return (cp.stdout or "").strip()[:40]
    except Exception:
        pass
    return "dev-unknown"


THIRAMAI_VERSION_ID = resolve_thiramai_version_id()


def effective_parallel_shell_enabled() -> bool:
    """Parallel shell batches disabled in safe mode (phase 60)."""
    return bool(THIRAMAI_PARALLEL_SHELL_ENABLED) and not THIRAMAI_SAFE_MODE


def effective_connector_http_strict() -> bool:
    """Safe mode forces strict HTTP connector policy (phase 60)."""
    return bool(THIRAMAI_CONNECTOR_HTTP_STRICT) or THIRAMAI_SAFE_MODE


_mode_raw = os.getenv("THIRAMAI_MODE", "simulation").strip().lower()
if _mode_raw in ("dry_run", "dryrun"):
    _mode_raw = "dry-run"
THIRAMAI_MODE_REQUESTED = _mode_raw if _mode_raw in {"dry-run", "simulation", "live"} else "simulation"


def is_openai_configured() -> bool:
    k = OPENAI_API_KEY
    return bool(k and k != "your_api_key_here")


if THIRAMAI_MODE_REQUESTED == "live" and not is_openai_configured():
    THIRAMAI_MODE = "dry-run"
    logger.warning(
        "[MODE] requested=live but OPENAI_API_KEY missing or placeholder; "
        "effective=dry-run (no crash)."
    )
else:
    THIRAMAI_MODE = THIRAMAI_MODE_REQUESTED


def get_thiramai_mode() -> str:
    """Effective execution mode: dry-run | simulation | live."""
    return THIRAMAI_MODE


def get_thiramai_mode_requested() -> str:
    """Value from env before live→dry-run coercion."""
    return THIRAMAI_MODE_REQUESTED
THIRAMAI_LOCATION = os.getenv("THIRAMAI_LOCATION", "Chennai").strip()
THIRAMAI_EVENT_DELTA_THRESHOLD = float(os.getenv("THIRAMAI_EVENT_DELTA_THRESHOLD", "0.15"))
THIRAMAI_WEATHER_API_URL = os.getenv("THIRAMAI_WEATHER_API_URL", "https://wttr.in").strip()
THIRAMAI_MARKET_API_URL = os.getenv(
    "THIRAMAI_MARKET_API_URL",
    "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd",
).strip()

# Self-heal / patch pipeline: run compile checks inside Docker before touching host files.
# sandbox = docker isolated test (default). live = skip Docker pre-check (dev/CI without Docker).
THIRAMAI_SANDBOX_MODE = os.getenv("THIRAMAI_SANDBOX_MODE", "sandbox").strip().lower()
THIRAMAI_SANDBOX_IMAGE = os.getenv("THIRAMAI_SANDBOX_IMAGE", "python:3.12-slim").strip()
THIRAMAI_SANDBOX_TIMEOUT_SEC = max(30, int(os.getenv("THIRAMAI_SANDBOX_TIMEOUT_SEC", "120")))


def _mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"


def validate_openai_api_key() -> str:
    """Require a real API key (live / real LLM paths only)."""
    key = OPENAI_API_KEY
    if not key or key == "your_api_key_here":
        raise RuntimeError(
            "OPENAI_API_KEY is missing in environment. Set it in project root .env, "
            "or use THIRAMAI_MODE=dry-run|simulation."
        )
    logger.info("OPENAI_API_KEY loaded: %s", _mask_secret(key))
    return key

ALLOWED_COMMANDS = {
    "ls",
    "dir",
    "pwd",
    "whoami",
    "echo",
    "docker",
    "docker-compose",
    "git",
    "python",
    "pip",
}

BLOCKED_TOKENS = {
    "rm",
    "rmdir",
    "del",
    "shutdown",
    "reboot",
    "mkfs",
    "dd",
    "chmod 777",
    ">",
    ">>",
    "|",
    "&",
}
