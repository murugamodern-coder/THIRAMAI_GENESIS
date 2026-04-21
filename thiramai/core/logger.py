from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SecurityLogger:
    def __init__(self, file_path: Path | None = None) -> None:
        default_path = Path(__file__).resolve().parent.parent.parent / "logs" / "audit_trail.jsonl"
        self.file_path = file_path or default_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._successful_tasks = 0
        self._blocked_tasks = 0

    def log(
        self,
        *,
        cycle_id: int,
        task_id: str,
        command: str,
        policy_decision: dict[str, Any],
        execution_status: str,
        risk_level: str,
        estimated_manual_minutes: float = 10.0,
        hourly_cost_rate: float = 500.0,
    ) -> None:
        status = str(execution_status).lower()
        if status == "success":
            self._successful_tasks += 1
        elif status == "blocked":
            self._blocked_tasks += 1
        cost_saved = 0.0
        if status == "success":
            cost_saved = max(0.0, float(estimated_manual_minutes)) / 60.0 * max(0.0, float(hourly_cost_rate))
        total_handled = max(1, self._successful_tasks + self._blocked_tasks)
        efficiency_gain = round((self._successful_tasks / total_handled) * 100.0, 2)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycle_id": int(cycle_id),
            "task_id": str(task_id),
            "command": str(command),
            "policy_decision": policy_decision,
            "execution_status": status,
            "risk_level": str(risk_level),
            "efficiency_gain_pct": efficiency_gain,
            "cost_saved_estimate": round(cost_saved, 2),
        }
        line = json.dumps(row, ensure_ascii=True)
        with self._lock:
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
