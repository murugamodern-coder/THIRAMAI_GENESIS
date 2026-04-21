"""
European Black–Scholes Greeks for index-style options (Nifty / Bank Nifty CE/PE).

Approximation: no dividend yield (q=0). ``theta`` returned as **change in option price per calendar day**
(typically negative for long options). ``vega`` is sensitivity per **1 percentage point** move in IV
(e.g. IV 18% → 19%).
"""

from __future__ import annotations

import math
import os
from typing import Any, Literal

OptionSide = Literal["call", "put"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_greeks(
    *,
    spot: float,
    strike: float,
    time_years: float,
    volatility: float,
    risk_free_rate: float,
    option_type: OptionSide,
) -> dict[str, Any]:
    """
    Returns delta, gamma, theta_per_day, vega_per_1pct_iv (call or put).
    """
    S = max(float(spot), 1e-9)
    K = max(float(strike), 1e-9)
    T = max(float(time_years), 1e-9)
    sigma = max(float(volatility), 1e-6)
    r = float(risk_free_rate)

    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    pdf_d1 = _norm_pdf(d1)
    cdf_d1 = _norm_cdf(d1)
    cdf_d2 = _norm_cdf(d2)
    cdf_m_d1 = _norm_cdf(-d1)
    cdf_m_d2 = _norm_cdf(-d2)

    disc = math.exp(-r * T)

    # Gamma (same for call/put under BS)
    gamma = pdf_d1 / (S * sigma * sqrt_t)

    if option_type == "call":
        delta = cdf_d1
        theta_year = -(S * pdf_d1 * sigma) / (2.0 * sqrt_t) - r * K * disc * cdf_d2
    else:
        delta = cdf_d1 - 1.0
        theta_year = -(S * pdf_d1 * sigma) / (2.0 * sqrt_t) + r * K * disc * cdf_m_d2

    theta_per_day = theta_year / 365.0

    # Vega per 1 unit absolute vol change; convert to per 1 percentage point (0.01)
    vega_per_unit_vol = S * sqrt_t * pdf_d1 * disc
    vega_per_1pct_iv = vega_per_unit_vol * 0.01

    return {
        "ok": True,
        "spot": round(S, 4),
        "strike": round(K, 4),
        "time_years": round(T, 8),
        "iv": round(sigma, 6),
        "risk_free_rate": r,
        "option_type": option_type,
        "delta": round(delta, 6),
        "gamma": round(gamma, 10),
        "theta_per_day": round(theta_per_day, 6),
        "vega_per_1pct_iv": round(vega_per_1pct_iv, 6),
    }


def default_risk_free_rate() -> float:
    try:
        return float((os.getenv("THIRAMAI_RISK_FREE_RATE") or "0.07").strip())
    except ValueError:
        return 0.07


def default_iv() -> float:
    try:
        return float((os.getenv("THIRAMAI_IV_DEFAULT") or "0.18").strip())
    except ValueError:
        return 0.18


def nifty_banknifty_option_greeks(
    *,
    underlying: Literal["nifty", "banknifty"],
    spot_inr: float,
    strike_inr: float,
    days_to_expiry: float,
    iv_annual: float | None = None,
    right: Literal["CE", "PE"],
) -> dict[str, Any]:
    """Convenience wrapper with CE→call, PE→put."""
    iv = float(iv_annual) if iv_annual is not None else default_iv()
    T = max(float(days_to_expiry), 0.25) / 365.0
    ot: OptionSide = "call" if right.upper() == "CE" else "put"
    g = black_scholes_greeks(
        spot=spot_inr,
        strike=strike_inr,
        time_years=T,
        volatility=iv,
        risk_free_rate=default_risk_free_rate(),
        option_type=ot,
    )
    g["underlying"] = underlying
    g["right"] = right.upper()
    return g
