from typing import Any

import httpx

from thiramai.config import THIRAMAI_MARKET_API_URL


def get_market_prices() -> dict[str, Any]:
    try:
        response = httpx.get(THIRAMAI_MARKET_API_URL, timeout=10)
        response.raise_for_status()
        payload = response.json()
        return {
            "source": "market_api",
            "prices": payload,
            "ok": True,
        }
    except Exception as exc:
        return {
            "source": "market_api",
            "prices": {},
            "ok": False,
            "error": str(exc),
        }
