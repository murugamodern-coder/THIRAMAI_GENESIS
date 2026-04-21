from typing import Any

import httpx

from thiramai.config import THIRAMAI_WEATHER_API_URL


def get_weather(location: str) -> dict[str, Any]:
    target = location.strip() or "Chennai"
    url = f"{THIRAMAI_WEATHER_API_URL}/{target}"
    try:
        response = httpx.get(url, params={"format": "j1"}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        current = (payload.get("current_condition") or [{}])[0]
        return {
            "source": "wttr",
            "location": target,
            "temperature_c": current.get("temp_C"),
            "humidity": current.get("humidity"),
            "description": ((current.get("weatherDesc") or [{}])[0]).get("value", ""),
            "ok": True,
        }
    except Exception as exc:
        return {
            "source": "wttr",
            "location": target,
            "ok": False,
            "error": str(exc),
        }
