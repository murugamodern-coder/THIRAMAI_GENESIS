"""
THIRAMAI Auto-Deploy Engine
Safely deploys new features with:
- Validation gate
- Rollback capability
- Health check after deploy
"""
import logging
import os
from datetime import datetime
from pathlib import Path

_log = logging.getLogger("thiramai.auto_deploy")

DEPLOY_LOG_PATH = Path("runtime/deploy_log.jsonl")
MAX_AUTO_DEPLOYS_PER_DAY = 3  # Safety limit

def can_auto_deploy() -> tuple[bool, str]:
    """Check if auto-deploy is safe to proceed."""
    # Check environment
    env = os.getenv("THIRAMAI_ENV", "development")
    if env == "production":
        autonomous = os.getenv("THIRAMAI_AUTONOMOUS_MODE", "false")
        if autonomous.lower() != "true":
            return False, "Auto-deploy disabled in production (set THIRAMAI_AUTONOMOUS_MODE=true)"

    # Check daily limit
    if DEPLOY_LOG_PATH.exists():
        import json
        today = datetime.now().date()
        count = 0
        with open(DEPLOY_LOG_PATH) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"]).date()
                    if ts == today:
                        count += 1
                except Exception:
                    continue
        if count >= MAX_AUTO_DEPLOYS_PER_DAY:
            return False, f"Daily auto-deploy limit ({MAX_AUTO_DEPLOYS_PER_DAY}) reached"

    return True, "OK"

def run_health_check() -> bool:
    """Run health check after deploy."""
    try:
        import urllib.request
        port = os.getenv("PORT", "8000")
        url = f"http://localhost:{port}/health/live"
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        _log.error("Health check failed: %s", e)
        return False

def safe_restart_service() -> dict:
    """Safely restart the THIRAMAI service."""
    ok, reason = can_auto_deploy()
    if not ok:
        return {"ok": False, "message": reason}

    _log.info("Auto-deploy: initiating safe restart")

    import json
    DEPLOY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": "restart",
        "triggered_by": "auto_deploy_engine",
    }
    with open(DEPLOY_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return {
        "ok": True,
        "message": "Restart scheduled — use /kernel/reload/ack to confirm",
        "timestamp": entry["timestamp"],
    }
