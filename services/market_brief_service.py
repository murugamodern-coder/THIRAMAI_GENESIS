"""Morning-style market brief: indices, watchlist, intraday-style opportunities, sentiment (Part D)."""

from __future__ import annotations

import logging
from typing import Any

from services.portfolio_service import list_watchlist_symbols_sync
from services.stock_market_jarvis import get_index_snapshot_sync, morning_market_brief_sync as _core_watchlist_brief
from services.stock_signal_service import generate_intraday_signal

_log = logging.getLogger("thiramai.market_brief")


def morning_market_brief_sync(*, user_id: int | None = None) -> dict[str, Any]:
    """
    Combines index snapshot, watchlist swing signals, and top intraday-style opportunities.

    ``user_id`` enables personalized watchlist + personalized intraday signals (risk limits apply).
    """
    syms = list_watchlist_symbols_sync(int(user_id or 0), limit=12) if user_id else []
    if not syms:
        syms = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]

    base = _core_watchlist_brief(watchlist_symbols=syms)
    nifty = base.get("nifty") or get_index_snapshot_sync("^NSEI")
    chg = float(nifty.get("change_pct") or 0) if isinstance(nifty, dict) else 0.0
    if chg > 0.25:
        sentiment = "risk-on / constructive"
    elif chg < -0.25:
        sentiment = "cautious / risk-off"
    else:
        sentiment = "balanced / range-bound"

    opportunities: list[dict[str, Any]] = []
    uid = int(user_id or 0) or None
    for sym in syms[:10]:
        try:
            sig = generate_intraday_signal(sym, user_id=uid, exchange_suffix="NS")
        except Exception as exc:
            _log.debug("signal %s: %s", sym, exc)
            continue
        if not sig.get("ok"):
            continue
        act = str(sig.get("action") or "HOLD")
        if act in ("BUY", "SELL"):
            opportunities.append(
                {
                    "symbol": sym,
                    "action": act,
                    "entry_price": sig.get("entry_price"),
                    "target_price": sig.get("target_price"),
                    "stop_loss": sig.get("stop_loss"),
                    "risk_reward": sig.get("risk_reward"),
                    "reasoning": sig.get("reasoning"),
                    "risk_blocked": sig.get("risk_blocked"),
                }
            )

    def _opp_key(o: dict[str, Any]) -> tuple[int, float]:
        rank = 0 if o.get("action") == "BUY" else 1 if o.get("action") == "SELL" else 2
        rr = float(o.get("risk_reward") or 0)
        return (rank, -rr)

    opportunities.sort(key=_opp_key)
    top3 = opportunities[:3]

    trending: list[dict[str, Any]] = []
    for row in (base.get("watchlist_signals") or [])[:6]:
        if not isinstance(row, dict):
            continue
        trending.append(
            {
                "symbol": row.get("symbol"),
                "swing_signal": row.get("signal"),
                "current_price": row.get("current_price"),
                "rsi": row.get("rsi"),
            }
        )

    out = dict(base)
    out["intraday_opportunities_top3"] = top3
    out["trending_stocks"] = trending
    out["market_sentiment"] = sentiment
    out["nifty_change_pct"] = chg
    return out
