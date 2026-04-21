from typing import Any

import shutil
import time


def get_system_status() -> dict[str, Any]:
    usage = shutil.disk_usage(".")
    return {
        "timestamp": int(time.time()),
        "disk_total_gb": round(usage.total / (1024**3), 2),
        "disk_used_gb": round(usage.used / (1024**3), 2),
        "disk_free_gb": round(usage.free / (1024**3), 2),
        "disk_free_ratio": round(usage.free / usage.total, 4) if usage.total else 0.0,
        "ok": True,
    }
