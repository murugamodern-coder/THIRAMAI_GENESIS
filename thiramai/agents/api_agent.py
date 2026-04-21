from typing import Any

import httpx


class APIAgent:
    ALLOWED_METHODS = {"GET"}

    def execute(self, task: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        method = str(task.get("method", "GET")).upper()
        if method not in self.ALLOWED_METHODS:
            return {
                "status": "blocked",
                "returncode": -1,
                "output": "",
                "error": f"HTTP method `{method}` is not allowed.",
            }

        url = str(task.get("api_url", "")).strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            return {
                "status": "blocked",
                "returncode": -1,
                "output": "",
                "error": "Invalid or missing api_url.",
            }

        try:
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            payload = response.text[:5000]
            return {
                "status": "success",
                "returncode": 0,
                "output": payload,
                "error": "",
                "api_status_code": response.status_code,
            }
        except Exception as exc:
            return {
                "status": "error",
                "returncode": -1,
                "output": "",
                "error": str(exc),
            }
