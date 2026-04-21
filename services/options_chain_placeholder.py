"""
Placeholder Nifty / Bank Nifty option chain feed — swap for Zerodha/Fyers API later.

Returns synthetic strikes + a deterministic CE/PE recommendation for Jarvis demos.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


def _spot_from_seed(seed: str) -> float:
    """Stable pseudo-spot near real Nifty for reproducible demos."""
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return 24000.0 + (h % 2000)


def fetch_nifty_option_chain_placeholder(
    *,
    underlying: str = "NIFTY",
    spot_hint: float | None = None,
) -> dict[str, Any]:
    """
    Replace with live chain API. ``recommended`` picks one CE strike near ATM + one PE hedge placeholder.
    """
    und = (underlying or "NIFTY").strip().upper()
    spot = float(spot_hint) if spot_hint and spot_hint > 0 else _spot_from_seed(und)
    step = float((os.getenv("THIRAMAI_OPTION_STRIKE_STEP") or "50").strip() or "50")
    atm = round(spot / step) * step
    lot = int((os.getenv("THIRAMAI_NIFTY_OPTIONS_LOT_SIZE") or "65").strip() or "65")
    expiry = (date.today() + timedelta(days=(3 - date.today().weekday()) % 7 or 7)).isoformat()

    strikes: list[dict[str, Any]] = []
    for i in range(-4, 5):
        k = atm + i * step
        ce_prem = max(5.0, abs(atm - k) * 0.35 + 25.0)
        pe_prem = max(5.0, abs(k - atm) * 0.35 + 22.0)
        strikes.append(
            {
                "strike": k,
                "ce_ltp_inr": round(ce_prem, 2),
                "pe_ltp_inr": round(pe_prem, 2),
                "oi_ce": 100_000 + i * 2500,
                "oi_pe": 95_000 - i * 1800,
            }
        )

    rec_ce_strike = atm + step
    rec_pe_strike = atm - step
    ce_row = next((x for x in strikes if x["strike"] == rec_ce_strike), strikes[len(strikes) // 2 + 1])
    pe_row = next((x for x in strikes if x["strike"] == rec_pe_strike), strikes[len(strikes) // 2 - 1])

    return {
        "ok": True,
        "source": "placeholder",
        "underlying": und,
        "spot_inr_approx": round(spot, 2),
        "expiry_next_weekly": expiry,
        "strike_step": step,
        "lot_size": lot,
        "strikes": strikes,
        "recommended": {
            "direction_bias": "STRUCTURAL_PLACEHOLDER",
            "primary": {
                "right": "CE",
                "strike": ce_row["strike"],
                "premium_inr_per_share": ce_row["ce_ltp_inr"],
                "rationale": "ATM+1 CE — momentum stub (replace with Greeks + IV)",
            },
            "secondary_context": {
                "right": "PE",
                "strike": pe_row["strike"],
                "premium_inr_per_share": pe_row["pe_ltp_inr"],
                "rationale": "ATM-1 PE — hedge reference (placeholder)",
            },
        },
    }


def fetch_banknifty_option_chain_placeholder(
    *,
    spot_hint: float | None = None,
) -> dict[str, Any]:
    base = fetch_nifty_option_chain_placeholder(underlying="BANKNIFTY", spot_hint=spot_hint or 52000.0)
    base["underlying"] = "BANKNIFTY"
    prim = base.get("recommended", {}).get("primary")
    if isinstance(prim, dict):
        prim["rationale"] = "Bank Nifty ATM+1 CE — placeholder chain (swap for live broker API)"
    return base
