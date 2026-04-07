"""
Live Indian equity quotes (Yahoo Finance via yfinance; optional Alpha Vantage) and price-move alerts.

Fuzzy resolution uses ``indian_equity_universe`` + rapidfuzz against NSE-oriented names.
"""

from __future__ import annotations

import os
import re
import time
from decimal import Decimal
from typing import Any

import httpx
import difflib

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein
from sqlalchemy import select

from core.database import get_session_factory
from core.db.models import ResearchVault
from services.indian_equity_universe import INDIAN_EQUITIES, row_by_base, row_by_yahoo

# (monotonic_expiry, price, currency)
_quote_cache: dict[str, tuple[float, Decimal, str]] = {}
_CACHE_TTL_SEC = 55.0

FUZZY_SCORE_CUTOFF = 72
FUZZY_SCORE_COMPANY_TOPIC = 68


def _parse_env_pct(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _cache_get(sym: str) -> tuple[Decimal | None, str] | None:
    ent = _quote_cache.get(sym)
    if not ent:
        return None
    exp, price, ccy = ent
    if time.monotonic() > exp:
        del _quote_cache[sym]
        return None
    return price, ccy


def _cache_set(sym: str, price: Decimal | None, ccy: str) -> None:
    if price is None:
        return
    _quote_cache[sym] = (time.monotonic() + _CACHE_TTL_SEC, price, ccy or "INR")


def fetch_quote_alpha_vantage(yahoo_symbol: str) -> tuple[Decimal | None, str]:
    key = (os.getenv("THIRAMAI_ALPHA_VANTAGE_API_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip()
    if not key:
        return None, "INR"
    base = yahoo_symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    if not base:
        return None, "INR"
    url = "https://www.alphavantage.co/query"
    params = {"function": "GLOBAL_QUOTE", "symbol": base, "apikey": key}
    try:
        with httpx.Client(timeout=12.0) as client:
            r = client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return None, "INR"
    gq = data.get("Global Quote") or data.get("Global quote") or {}
    raw = gq.get("05. price") or gq.get("5. price")
    if raw is None:
        return None, "INR"
    try:
        return Decimal(str(raw)), "INR"
    except Exception:
        return None, "INR"


def fetch_quote_yfinance(yahoo_symbol: str) -> tuple[Decimal | None, str]:
    cached = _cache_get(yahoo_symbol)
    if cached is not None:
        return cached[0], cached[1]
    sym = yahoo_symbol.strip()
    if not sym:
        return None, "INR"
    price: Decimal | None = None
    ccy = "INR"
    try:
        import yfinance as yf

        t = yf.Ticker(sym)
        fi = getattr(t, "fast_info", None)
        if fi is not None:
            if isinstance(fi, dict):
                for k in ("last_price", "lastPrice", "regularMarketPrice"):
                    if fi.get(k) is not None:
                        price = Decimal(str(fi[k]))
                        break
            else:
                lp = getattr(fi, "last_price", None) or getattr(fi, "lastPrice", None)
                if lp is not None:
                    price = Decimal(str(lp))
        if price is None:
            info = t.info or {}
            for k in ("regularMarketPrice", "currentPrice", "previousClose"):
                if info.get(k) is not None:
                    price = Decimal(str(info[k]))
                    break
            cur = info.get("currency")
            if isinstance(cur, str) and cur.strip():
                ccy = cur.strip().upper()[:8]
    except Exception:
        price = None

    if price is None:
        avp, avc = fetch_quote_alpha_vantage(sym)
        if avp is not None:
            price, ccy = avp, avc

    _cache_set(sym, price, ccy)
    return price, ccy


def _typo_near_token_score(q: str, row: dict[str, str]) -> float:
    """Boost when query is a close edit to a symbol or significant name token (e.g. Suslan ≈ Suzlon)."""
    q = q.strip().lower()
    if len(q) < 4:
        return 0.0
    tokens: list[str] = [row["base"].lower()]
    tokens.extend(re.findall(r"[a-z]{4,}", row["name"].lower()))
    best = 0.0
    for w in tokens:
        if abs(len(w) - len(q)) > 3:
            continue
        d = int(Levenshtein.distance(q, w))
        if d <= 1 and min(len(q), len(w)) >= 4:
            best = max(best, 96.0)
        elif d == 2 and min(len(q), len(w)) >= 5:
            best = max(best, 88.0)
    return best


def _equity_match_score(query_norm: str, row: dict[str, str]) -> float:
    """Combined fuzzy score so typos like 'Suslan' → Suzlon beat unrelated large caps."""
    base = row["base"].lower()
    name = row["name"].lower()
    blob = f"{base} {name}"
    q = query_norm.strip().lower()
    if not q:
        return 0.0
    return float(
        max(
            _typo_near_token_score(q, row),
            fuzz.WRatio(q, blob),
            fuzz.partial_ratio(q, base),
            fuzz.partial_ratio(q, name),
            fuzz.token_set_ratio(q, blob),
            fuzz.ratio(q, base),
        )
    )


def fuzzy_resolve_indian_equity(query: str, *, score_cutoff: int = FUZZY_SCORE_CUTOFF) -> dict[str, Any] | None:
    """
    Map a messy company name to the closest NSE-oriented Yahoo symbol.

    Returns dict: yahoo, base, name, label, score — or None if no confident match.
    """
    raw = (query or "").strip()
    if len(raw) < 2:
        return None

    m = re.match(r"^([A-Z0-9&.-]{1,20})\.(NS|BO)$", raw.upper())
    if m:
        yh = f"{m.group(1)}.{m.group(2)}"
        row = row_by_yahoo(yh) or row_by_base(m.group(1))
        if row:
            return {
                "yahoo": row["yahoo"],
                "base": row["base"],
                "name": row["name"],
                "label": f"{row['name']} ({row['yahoo']})",
                "score": 100.0,
            }
        return {
            "yahoo": yh,
            "base": m.group(1),
            "name": m.group(1),
            "label": yh,
            "score": 95.0,
        }

    qu = raw.upper()
    rb = row_by_base(qu)
    if rb:
        return {
            "yahoo": rb["yahoo"],
            "base": rb["base"],
            "name": rb["name"],
            "label": f"{rb['name']} ({rb['yahoo']})",
            "score": 100.0,
        }

    qnorm = raw.lower()
    base_keys = [r["base"].lower() for r in INDIAN_EQUITIES]
    close = difflib.get_close_matches(qnorm, base_keys, n=1, cutoff=0.74)
    if len(close) == 1:
        hit_base = close[0].upper()
        row_hit = row_by_base(hit_base)
        if row_hit:
            return {
                "yahoo": row_hit["yahoo"],
                "base": row_hit["base"],
                "name": row_hit["name"],
                "label": f"{row_hit['name']} ({row_hit['yahoo']})",
                "score": 94.0,
            }

    best_row: dict[str, str] | None = None
    best_score = 0.0
    for row in INDIAN_EQUITIES:
        s = _equity_match_score(qnorm, row)
        if s > best_score:
            best_score = s
            best_row = row
    if best_row is None or best_score < float(score_cutoff):
        return None
    row = best_row
    return {
        "yahoo": row["yahoo"],
        "base": row["base"],
        "name": row["name"],
        "label": f"{row['name']} ({row['yahoo']})",
        "score": best_score,
    }


def _looks_like_long_non_company_topic(topic: str) -> bool:
    t = topic.strip()
    if len(t) > 140:
        return True
    if t.count(" ") > 18:
        return True
    return False


def maybe_resolve_equity_for_topic(topic: str) -> dict[str, Any] | None:
    """
    Try fuzzy equity resolution when the topic is short / name-like.

    Uses a slightly lower cutoff for compact queries (e.g. typos like 'Suslan').
    """
    raw = (topic or "").strip()
    if not raw or _looks_like_long_non_company_topic(raw):
        return None
    cutoff = FUZZY_SCORE_COMPANY_TOPIC if len(raw) <= 36 else FUZZY_SCORE_CUTOFF
    return fuzzy_resolve_indian_equity(raw, score_cutoff=cutoff)


def list_equity_move_alerts_for_user_sync(*, user_id: int, max_symbols: int = 24) -> list[dict[str, Any]]:
    """
    For each symbol in the user's recent research vault rows, compare live price to ``price_at_save``.

    When absolute move exceeds threshold (default 3%), emit a bell-style item (``kind``: ``price_move``).
    """
    if (os.getenv("THIRAMAI_STOCK_ALERTS_ENABLED") or "1").strip().lower() in ("0", "false", "no"):
        return []
    uid = int(user_id)
    if uid <= 0:
        return []
    threshold_pct = _parse_env_pct("THIRAMAI_STOCK_ALERT_PCT", 3.0) / 100.0
    if threshold_pct <= 0:
        return []

    factory = get_session_factory()
    if factory is None:
        return []
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=120)
    now = datetime.now(timezone.utc)
    with factory() as session:
        rows = session.execute(
            select(ResearchVault)
            .where(
                ResearchVault.user_id == uid,
                ResearchVault.resolved_symbol.isnot(None),
                ResearchVault.price_at_save.isnot(None),
                ResearchVault.created_at >= cutoff,
            )
            .order_by(ResearchVault.created_at.desc())
        ).scalars().all()

    latest_by_sym: dict[str, ResearchVault] = {}
    for r in rows:
        sym = (r.resolved_symbol or "").strip()
        if not sym or sym in latest_by_sym:
            continue
        latest_by_sym[sym] = r
        if len(latest_by_sym) >= max_symbols:
            break

    alerts: list[dict[str, Any]] = []
    for sym, row in latest_by_sym.items():
        base_px = row.price_at_save
        if base_px is None or base_px <= 0:
            continue
        live, _ccy = fetch_quote_yfinance(sym)
        if live is None or live <= 0:
            continue
        try:
            delta = (live - Decimal(base_px)) / Decimal(base_px)
            pct = float(delta) * 100.0
        except Exception:
            continue
        if abs(pct) < threshold_pct * 100.0 - 1e-9:
            continue
        direction = "up" if pct > 0 else "down"
        title = f"{sym} {direction} {abs(pct):.2f}% vs your research snapshot (₹{base_px} → live)"
        alerts.append(
            {
                "id": f"stock:{sym}",
                "title": title,
                "remind_at": now.isoformat(),
                "overdue": False,
                "kind": "price_move",
                "symbol": sym,
                "pct_change": round(pct, 2),
                "baseline_price": str(base_px),
                "live_price": str(live),
            }
        )
    alerts.sort(key=lambda x: abs(float(x.get("pct_change") or 0)), reverse=True)
    return alerts
