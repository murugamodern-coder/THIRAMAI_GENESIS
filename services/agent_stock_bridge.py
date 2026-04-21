"""
Trading OS execution helpers — mirrors ``api/routes/stock_assistant.py`` service calls + risk sizing.

Quantity uses ``THIRAMAI_TRADE_RISK_PERCENT`` (default 2%) of deployable capital:
portfolio ``total_current_value_inr`` when non-zero, else ``THIRAMAI_TRADING_CAPITAL_INR``.

Smart sizing (options): reduces lots when theta decay vs premium is high or when Tavily/Groq
sentiment contradicts the intraday technical signal.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Callable

from services.portfolio_service import get_portfolio_summary_sync
from services.security.vault_service import sentiment_overlay_active, smart_sizing_active
from services.stock_indicator_service import analyze_indicators
from services.stock_market_data_service import get_live_price
from services.stock_signal_service import generate_intraday_signal

LogFn = Callable[[str], None]


def _risk_percent() -> Decimal:
    try:
        return Decimal(str((os.getenv("THIRAMAI_TRADE_RISK_PERCENT") or "2").strip()))
    except Exception:
        return Decimal("2")


def trading_capital_inr(user_id: int) -> Decimal:
    """Deployable notional for sizing (paper portfolio value or env fallback)."""
    uid = int(user_id)
    if uid > 0:
        summ = get_portfolio_summary_sync(uid)
        if summ.get("ok"):
            try:
                tv = Decimal(str(summ.get("total_current_value_inr") or "0"))
                if tv > 0:
                    return tv
            except Exception:
                pass
    raw = (os.getenv("THIRAMAI_TRADING_CAPITAL_INR") or "").strip()
    if raw:
        try:
            return Decimal(raw)
        except Exception:
            pass
    return Decimal("100000")


def equity_quantity_for_risk(
    user_id: int,
    *,
    last_price_inr: Decimal,
    risk_pct: Decimal | None = None,
) -> dict[str, Any]:
    capital = trading_capital_inr(user_id)
    pct = risk_pct if risk_pct is not None else _risk_percent()
    risk_inr = (capital * pct / Decimal("100")).quantize(Decimal("0.01"))
    if last_price_inr <= 0:
        return {
            "ok": False,
            "quantity_shares": 0,
            "risk_inr": str(risk_inr),
            "capital_basis_inr": str(capital),
            "risk_percent": str(pct),
            "error": "invalid price for sizing",
        }
    qty = int(risk_inr // last_price_inr)
    return {
        "ok": True,
        "quantity_shares": qty,
        "risk_inr": str(risk_inr),
        "capital_basis_inr": str(capital),
        "risk_percent": str(pct),
        "notional_inr": str((Decimal(qty) * last_price_inr).quantize(Decimal("0.01"))),
    }


def _theta_ratio_max() -> Decimal:
    try:
        return Decimal(str((os.getenv("THIRAMAI_THETA_DECAY_RATIO_MAX") or "0.14").strip()))
    except Exception:
        return Decimal("0.14")


def _sentiment_contradiction_abs() -> float:
    try:
        return float((os.getenv("THIRAMAI_SENTIMENT_CONTRADICTION_ABS") or "0.38").strip())
    except ValueError:
        return 0.38


def smart_adjust_option_lots(
    base_lots: int,
    *,
    premium_per_share_inr: Decimal,
    theta_per_day: float | None,
    sentiment_score: float | None,
    technical_action: str | None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Reduce ``base_lots`` when time-decay dominates premium or headline sentiment clashes with ``technical_action``
    (expects BUY / SELL / HOLD).
    """
    reasons: list[str] = []
    lots = max(0, int(base_lots))
    if user_id and user_id > 0 and not smart_sizing_active(user_id):
        return {
            "lots_base": lots,
            "lots_adjusted": lots,
            "multiplier": "1",
            "adjustment_reasons": ["smart_sizing_disabled_for_user"],
        }
    mult = Decimal("1")
    ta = str(technical_action or "").strip().upper()
    sc = float(sentiment_score) if sentiment_score is not None else None

    prem = Decimal(str(premium_per_share_inr))
    if prem > 0 and theta_per_day is not None:
        decay_ratio = abs(float(theta_per_day)) / float(prem)
        if Decimal(str(decay_ratio)) > _theta_ratio_max():
            mult *= Decimal("0.5")
            reasons.append(
                f"theta_decay_ratio={decay_ratio:.4f}>{float(_theta_ratio_max())} — halved lots (time decay vs premium)"
            )

    thr = _sentiment_contradiction_abs()
    if sc is not None:
        if ta == "BUY" and sc < -thr:
            mult *= Decimal("0.5")
            reasons.append(f"sentiment {sc:.2f} contradicts BUY — halved lots")
        elif ta == "SELL" and sc > thr:
            mult *= Decimal("0.5")
            reasons.append(f"sentiment {sc:.2f} contradicts SELL — halved lots")

    adjusted = int(Decimal(lots) * mult)
    return {
        "lots_base": lots,
        "lots_adjusted": adjusted,
        "multiplier": str(mult.quantize(Decimal("0.01"))),
        "adjustment_reasons": reasons,
    }


def smart_adjust_equity_quantity(
    base_qty: int,
    *,
    sentiment_score: float | None,
    technical_action: str | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    qty = max(0, int(base_qty))
    mult = Decimal("1")
    ta = str(technical_action or "").strip().upper()
    sc = float(sentiment_score) if sentiment_score is not None else None
    thr = _sentiment_contradiction_abs()
    if sc is not None:
        if ta == "BUY" and sc < -thr:
            mult *= Decimal("0.5")
            reasons.append(f"sentiment {sc:.2f} vs BUY — halved shares")
        elif ta == "SELL" and sc > thr:
            mult *= Decimal("0.5")
            reasons.append(f"sentiment {sc:.2f} vs SELL — halved shares")
    adj = int(Decimal(qty) * mult)
    return {
        "quantity_shares_base": qty,
        "quantity_shares_adjusted": adj,
        "multiplier": str(mult.quantize(Decimal("0.01"))),
        "adjustment_reasons": reasons,
    }


def option_lots_for_risk(
    user_id: int,
    *,
    premium_per_share_inr: Decimal,
    lot_size: int,
    risk_pct: Decimal | None = None,
) -> dict[str, Any]:
    capital = trading_capital_inr(user_id)
    pct = risk_pct if risk_pct is not None else _risk_percent()
    risk_inr = (capital * pct / Decimal("100")).quantize(Decimal("0.01"))
    per_lot = (premium_per_share_inr * Decimal(lot_size)).quantize(Decimal("0.01"))
    if per_lot <= 0:
        return {
            "ok": False,
            "lots": 0,
            "risk_inr": str(risk_inr),
            "premium_per_lot_inr": str(per_lot),
        }
    lots = int(risk_inr // per_lot)
    return {
        "ok": True,
        "lots": lots,
        "risk_inr": str(risk_inr),
        "capital_basis_inr": str(capital),
        "risk_percent": str(pct),
        "premium_per_lot_inr": str(per_lot),
    }


def apply_sentiment_overlay_to_bundle(
    bundle: dict[str, Any],
    *,
    sentiment_payload: dict[str, Any],
    log: LogFn | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Mutates bundle: attaches ``market_sentiment`` and adjusts ``risk_sizing`` when equity sizing exists."""
    _log = log or (lambda _m: None)
    if user_id and user_id > 0 and not smart_sizing_active(user_id):
        _log("Sentiment overlay skipped (smart sizing disabled — unified with options path).")
        bundle["market_sentiment"] = {"ok": True, "skipped": True, "reason": "smart_sizing_disabled"}
        return bundle
    if user_id and user_id > 0 and not sentiment_overlay_active(user_id):
        _log("Sentiment overlay skipped (disabled in runtime config).")
        bundle["market_sentiment"] = {"ok": True, "skipped": True, "reason": "overlay_disabled"}
        return bundle
    bundle["market_sentiment"] = sentiment_payload
    rs = bundle.get("risk_sizing")
    if not isinstance(rs, dict) or not rs.get("ok"):
        return bundle
    sig = bundle.get("signal") if isinstance(bundle.get("signal"), dict) else {}
    ta = str(sig.get("action") or sig.get("signal") or "").strip().upper()
    try:
        base_q = int(rs.get("quantity_shares") or 0)
    except Exception:
        base_q = 0
    sc = sentiment_payload.get("score")
    adj = smart_adjust_equity_quantity(base_q, sentiment_score=float(sc) if sc is not None else None, technical_action=ta)
    rs["quantity_shares_before_sentiment"] = base_q
    rs["quantity_shares"] = adj["quantity_shares_adjusted"]
    rs["sentiment_adjustment"] = adj
    if adj["adjustment_reasons"]:
        _log("Sentiment overlay reduced equity size: " + "; ".join(adj["adjustment_reasons"]))
    return bundle


def run_equity_trade_bundle(
    symbol: str,
    user_id: int | None,
    *,
    exchange_suffix: str = "NS",
    depth: str = "full",
    log: LogFn | None = None,
    include_market_sentiment: bool = True,
) -> dict[str, Any]:
    """
    Same data path as ``GET /stocks/assistant/quote|analyze|signal`` — bundled for agent steps.
    """
    _log = log or (lambda _m: None)
    sym = (symbol or "").strip().upper()
    _log(f"Fetching live quote for {sym}...")
    quote = get_live_price(sym, exchange_suffix=exchange_suffix)
    out: dict[str, Any] = {"ok": True, "symbol": sym, "exchange_suffix": exchange_suffix, "quote": quote}

    if depth in ("full", "analyze", "signal"):
        _log(f"Loading technicals (RSI/MACD/EMA) for {sym}...")
        out["indicators"] = analyze_indicators(sym, interval="5m", exchange_suffix=exchange_suffix)
        _log("Generating rule-based intraday signal...")
        uid = user_id if user_id and user_id > 0 else None
        out["signal"] = generate_intraday_signal(sym, user_id=uid, exchange_suffix=exchange_suffix)

    last = None
    if quote.get("ok"):
        try:
            last = Decimal(str(quote.get("last")))
        except Exception:
            last = None
    if last and last > 0 and user_id and user_id > 0:
        _log(f"Sizing position at {_risk_percent()}% of capital vs last {last} INR...")
        out["risk_sizing"] = equity_quantity_for_risk(user_id, last_price_inr=last)

    if include_market_sentiment and user_id and user_id > 0 and smart_sizing_active(user_id) and sentiment_overlay_active(user_id):
        _log("Computing market sentiment score (Tavily + Groq, ~2h window)...")
        try:
            from services.research_common import market_sentiment_score_sync

            sent = market_sentiment_score_sync(window_hours=2)
            apply_sentiment_overlay_to_bundle(out, sentiment_payload=sent, log=_log, user_id=user_id)
        except Exception as exc:
            out["market_sentiment"] = {"ok": False, "score": 0.0, "summary": str(exc)[:200]}
    elif include_market_sentiment and user_id and user_id > 0:
        if not smart_sizing_active(user_id):
            out["market_sentiment"] = {"ok": True, "skipped": True, "reason": "smart_sizing_disabled"}
        else:
            out["market_sentiment"] = {"ok": True, "skipped": True, "reason": "sentiment_overlay_disabled"}

    return out


def is_options_trade_context(symbol: str, params: dict[str, Any]) -> bool:
    if str(params.get("instrument") or "").lower() == "options":
        return True
    ch = str(params.get("chain") or "").lower()
    if ch in ("nifty", "banknifty", "bnf", "sensex"):
        return True
    u = (symbol or "").strip().upper()
    if u in ("NIFTY", "BANKNIFTY", "^NSEI"):
        return True
    return "option" in str(params.get("depth") or "").lower()


def build_trade_step_preview(
    user_id: int,
    symbol: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Lightweight context for pending trade steps (Greeks + sentiment) without executing orders.
    """
    from datetime import date as date_cls

    from services.options_chain_placeholder import (
        fetch_banknifty_option_chain_placeholder,
        fetch_nifty_option_chain_placeholder,
    )
    from services.research_common import market_sentiment_score_sync
    from services.stock_market_jarvis import get_index_snapshot_sync
    from services.trading.greeks_calculator import nifty_banknifty_option_greeks

    if user_id and user_id > 0 and not smart_sizing_active(user_id):
        sent = {"ok": True, "skipped": True, "reason": "smart_sizing_disabled"}
    elif user_id and user_id > 0 and not sentiment_overlay_active(user_id):
        sent = {"ok": True, "skipped": True, "reason": "sentiment_overlay_disabled"}
    else:
        sent = market_sentiment_score_sync(window_hours=2)
    out: dict[str, Any] = {"market_sentiment": sent, "symbol": (symbol or "").strip().upper()}

    if not is_options_trade_context(symbol, params):
        return out

    idx = get_index_snapshot_sync("^NSEI")
    spot = float(idx["last"]) if idx.get("ok") else None
    ch = str(params.get("chain") or "").lower()
    sym_u = (symbol or "").strip().upper()
    if ch == "banknifty" or sym_u == "BANKNIFTY":
        chain = fetch_banknifty_option_chain_placeholder(spot_hint=spot)
        und = "banknifty"
    else:
        chain = fetch_nifty_option_chain_placeholder(spot_hint=spot)
        und = "nifty"

    rec = chain.get("recommended") or {}
    prim = rec.get("primary") if isinstance(rec.get("primary"), dict) else {}
    spot_use = float(chain.get("spot_inr_approx") or spot or 24000)
    strike_k = float(prim.get("strike") or 0)
    right = str(prim.get("right") or "CE").upper()
    prem = prim.get("premium_inr_per_share")
    exp = str(chain.get("expiry_next_weekly") or "")
    try:
        ed = date_cls.fromisoformat(exp[:10])
        dte = float(max(1, (ed - date_cls.today()).days))
    except Exception:
        dte = 5.0

    if strike_k > 0 and prem is not None:
        g = nifty_banknifty_option_greeks(
            underlying=und,
            spot_inr=spot_use,
            strike_inr=strike_k,
            days_to_expiry=dte,
            right="CE" if right == "CE" else "PE",
        )
        out["greeks"] = g
        out["option_hint"] = {
            "underlying": chain.get("underlying"),
            "strike": strike_k,
            "right": right,
            "premium_inr_per_share": prem,
            "days_to_expiry": dte,
        }
    out["chain_preview"] = {"underlying": chain.get("underlying"), "expiry_next_weekly": chain.get("expiry_next_weekly")}
    return out
