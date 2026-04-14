"""
Upgrade 4 — real-time equity monitor: batched quotes, price alerts, risk cap, indicator signals.

Market data path: **yfinance / nsepython** via ``get_live_price`` (same as stock assistant). Optional NSE/BSE
native WebSocket feeds can be wired later behind ``THIRAMAI_STOCK_MARKET_WS_URL`` without changing the public
``StockRealtimeMonitor`` API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from services.portfolio_service import (
    daily_equity_pnl_inr_sync,
    get_portfolio_summary_sync,
    list_watchlist_symbols_sync,
)
from services.stock_alert_service import add_stock_price_alert_sync, list_stock_alerts_sync
from services.stock_indicator_service import analyze_indicators
from services.stock_market_data_service import get_live_price

_log = logging.getLogger("thiramai.stock_realtime")


def _cooldown_key(user_id: int, kind: str, sub: str) -> str:
    return f"{int(user_id)}:{kind}:{sub}"


def _max_daily_loss_inr() -> Decimal:
    try:
        return Decimal(str((os.getenv("THIRAMAI_MAX_DAILY_LOSS_INR") or "2000").strip()))
    except Exception:
        return Decimal("2000")


def _alert_cooldown_sec() -> float:
    try:
        return max(30.0, min(600.0, float((os.getenv("THIRAMAI_STOCK_ALERT_COOLDOWN_SEC") or "90").strip())))
    except ValueError:
        return 90.0


class StockRealtimeMonitor:
    """
    In-memory coordination for watchlists, alert rules, and open positions (mirrors DB).

    WebSocket subscribers receive ``stock_tick`` payloads on a fixed poll interval.
    """

    def __init__(self) -> None:
        self.watchlists: dict[int, list[str]] = {}
        self.alerts: dict[int, list[dict[str, Any]]] = {}
        self.positions: dict[int, list[dict[str, Any]]] = {}
        self._subscribers: dict[int, list[asyncio.Queue]] = defaultdict(list)
        self._user_refs: dict[int, int] = {}
        self._user_org: dict[int, int | None] = {}
        self._alert_cooldown: dict[str, float] = {}
        self._signal_state: dict[str, dict[str, Any]] = {}
        self._risk_sent: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        self._poll_lock = asyncio.Lock()

    def poll_interval_sec(self) -> float:
        raw = (os.getenv("THIRAMAI_STOCK_WS_POLL_SEC") or "5").strip()
        try:
            return max(2.0, min(60.0, float(raw)))
        except ValueError:
            return 5.0

    def register_subscriber(self, user_id: int, queue: asyncio.Queue, *, organization_id: int | None = None) -> None:
        uid = int(user_id)
        self._subscribers[uid].append(queue)
        self._user_refs[uid] = self._user_refs.get(uid, 0) + 1
        if organization_id is not None and int(organization_id) > 0:
            self._user_org[uid] = int(organization_id)

    def push_synthetic_tick(self, user_id: int, payload: dict[str, Any]) -> None:
        """Enqueue a payload for tests or demos without waiting for the poll loop."""
        uid = int(user_id)
        for q in list(self._subscribers.get(uid, [])):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def unregister_subscriber(self, user_id: int, queue: asyncio.Queue) -> None:
        uid = int(user_id)
        lst = self._subscribers.get(uid) or []
        if queue in lst:
            lst.remove(queue)
        self._user_refs[uid] = max(0, self._user_refs.get(uid, 1) - 1)
        if self._user_refs.get(uid, 0) <= 0:
            self._user_refs.pop(uid, None)
            self.watchlists.pop(uid, None)
            self.alerts.pop(uid, None)
            self.positions.pop(uid, None)
            self._user_org.pop(uid, None)

    def active_users(self) -> list[int]:
        return [k for k, v in self._user_refs.items() if v > 0]

    async def ensure_poll_task(self) -> None:
        async with self._poll_lock:
            if self._poll_task is None or self._poll_task.done():
                self._poll_task = asyncio.create_task(self._run_poll_forever(), name="stock_realtime_poll")

    async def _run_poll_forever(self) -> None:
        try:
            while True:
                users = self.active_users()
                if not users:
                    await asyncio.sleep(1.0)
                    continue
                for uid in users:
                    payload = await asyncio.to_thread(self.compose_tick_sync, uid)
                    for q in list(self._subscribers.get(uid, [])):
                        try:
                            q.put_nowait(payload)
                        except asyncio.QueueFull:
                            try:
                                q.get_nowait()
                            except Exception:
                                pass
                            try:
                                q.put_nowait(payload)
                            except Exception:
                                pass
                await asyncio.sleep(self.poll_interval_sec())
        except asyncio.CancelledError:
            return

    def add_price_alert(
        self,
        user_id: int,
        symbol: str,
        condition: str,
        price: float | Decimal | str | None,
        action: str,
        *,
        reference_price: float | Decimal | str | None = None,
        percent_threshold: float | Decimal | str | None = None,
        exchange_suffix: str = "NS",
    ) -> dict[str, Any]:
        return add_stock_price_alert_sync(
            int(user_id),
            symbol=symbol,
            condition=condition,
            price=price,
            action=action,
            exchange_suffix=exchange_suffix,
            reference_price=reference_price,
            percent_threshold=percent_threshold,
        )

    def evaluate_alerts(self, user_id: int, prices: dict[str, dict[str, Any]], alert_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        uid = int(user_id)
        now = time.monotonic()
        cd = _alert_cooldown_sec()
        fired: list[dict[str, Any]] = []
        for a in alert_rows:
            aid = int(a.get("id") or 0)
            sym = str(a.get("symbol") or "").upper()
            if not sym or aid <= 0:
                continue
            pq = prices.get(sym) or {}
            if not pq.get("ok"):
                continue
            last = float(pq.get("last") or 0)
            if last <= 0:
                continue
            cond = str(a.get("condition") or "").lower()
            ck = _cooldown_key(uid, "alert", f"{aid}")
            if now - self._alert_cooldown.get(ck, 0) < cd:
                continue
            hit = False
            msg = ""
            if cond == "above":
                thr = float(a.get("price_threshold") or 0)
                if thr > 0 and last >= thr:
                    hit = True
                    msg = f"{sym} is at or above ₹{thr:.2f} (last ₹{last:.2f})"
            elif cond == "below":
                thr = float(a.get("price_threshold") or 0)
                if thr > 0 and last <= thr:
                    hit = True
                    msg = f"{sym} is at or below ₹{thr:.2f} (last ₹{last:.2f})"
            elif cond == "percent_change":
                ref_raw = a.get("reference_price")
                pct_thr = float(a.get("percent_threshold") or 0)
                if ref_raw is None or pct_thr <= 0:
                    continue
                ref = float(ref_raw)
                if ref <= 0:
                    continue
                move = abs((last - ref) / ref * 100.0)
                if move >= pct_thr:
                    hit = True
                    msg = f"{sym} moved {move:.2f}% vs reference ₹{ref:.2f} (threshold {pct_thr}%)"
            if hit:
                self._alert_cooldown[ck] = now
                fired.append(
                    {
                        "type": "price_alert",
                        "alert_id": aid,
                        "symbol": sym,
                        "message": msg,
                        "action": a.get("action") or "notify",
                        "last": last,
                    }
                )
        return fired

    def check_risk_limits(self, user_id: int) -> dict[str, Any] | None:
        uid = int(user_id)
        if uid <= 0:
            return None
        lim = _max_daily_loss_inr()
        pnl = daily_equity_pnl_inr_sync(uid)
        if pnl > -lim:
            return None
        day_key = f"{uid}:{date.today().isoformat()}"
        proactive_first = day_key not in self._risk_sent
        if proactive_first:
            self._risk_sent.add(day_key)
            oid = self._user_org.get(uid)
            if oid and int(oid) > 0:
                try:
                    from services.jarvis_proactive_service import upsert_equity_stop_trading_alert_sync

                    upsert_equity_stop_trading_alert_sync(
                        user_id=uid,
                        organization_id=int(oid),
                        daily_pnl_inr=pnl,
                        limit_inr=lim,
                    )
                except Exception as exc:
                    _log.debug("risk proactive: %s", exc)
        return {
            "type": "risk_stop",
            "title": "STOP TRADING",
            "message": f"Realized P&L today is ₹{pnl} (limit -₹{lim}). Pause new risk until next session.",
            "daily_realized_pnl_inr": str(pnl),
            "limit_inr": str(lim),
            "repeat": not proactive_first,
        }

    def detect_signal_events(self, user_id: int, symbol: str, ind: dict[str, Any]) -> list[dict[str, Any]]:
        if not ind.get("ok"):
            return []
        uid = int(user_id)
        sym = str(symbol or "").upper()
        key = f"{uid}:{sym}"
        prev = self._signal_state.get(key) or {}
        out: list[dict[str, Any]] = []
        ema9 = ind.get("ema9")
        ema21 = ind.get("ema21")
        hist = ind.get("macd_histogram")
        bull = None
        if ema9 is not None and ema21 is not None:
            bull = float(ema9) > float(ema21)
        prev_bull = prev.get("ema_bull")
        if bull is not None and prev_bull is not None and (not prev_bull) and bull:
            out.append(
                {
                    "type": "signal",
                    "kind": "ema_bullish_cross",
                    "symbol": sym,
                    "rsi": ind.get("rsi"),
                    "message": f"{sym}: EMA9 crossed above EMA21 (bullish alignment).",
                }
            )
        if bull is not None:
            prev["ema_bull"] = bull
        prev_hist = prev.get("macd_hist")
        if prev_hist is not None and hist is not None:
            try:
                ph = float(prev_hist)
                ch = float(hist)
                if ph < 0 <= ch:
                    out.append(
                        {
                            "type": "signal",
                            "kind": "macd_hist_cross_up",
                            "symbol": sym,
                            "macd_histogram": ch,
                            "message": f"{sym}: MACD histogram crossed above zero.",
                        }
                    )
            except (TypeError, ValueError):
                pass
        if hist is not None:
            try:
                prev["macd_hist"] = float(hist)
            except (TypeError, ValueError):
                pass
        self._signal_state[key] = prev
        return out

    def compose_tick_sync(self, user_id: int) -> dict[str, Any]:
        uid = int(user_id)
        ts = datetime.now(timezone.utc).isoformat()
        syms = list_watchlist_symbols_sync(uid)
        self.watchlists[uid] = list(syms)
        try:
            alert_rows = list_stock_alerts_sync(uid)
        except Exception as exc:
            _log.warning("list_stock_alerts_sync: %s", exc)
            alert_rows = []
        self.alerts[uid] = list(alert_rows)
        sym_set = set(syms)
        for a in alert_rows:
            s = str(a.get("symbol") or "").upper()
            if s:
                sym_set.add(s)
        prices: dict[str, dict[str, Any]] = {}
        for sym in sorted(sym_set):
            prices[sym] = dict(get_live_price(sym, exchange_suffix="NS"))
        port = get_portfolio_summary_sync(uid)
        pos = port.get("positions") if isinstance(port, dict) else []
        self.positions[uid] = list(pos) if isinstance(pos, list) else []
        alert_events = self.evaluate_alerts(uid, prices, alert_rows)
        risk = self.check_risk_limits(uid)
        signal_events: list[dict[str, Any]] = []
        for sym in syms[:24]:
            ind = analyze_indicators(sym, interval="5m", exchange_suffix="NS")
            signal_events.extend(self.detect_signal_events(uid, sym, ind))
        return {
            "type": "stock_tick",
            "channel": "ws/stocks",
            "as_of_utc": ts,
            "user_id": uid,
            "prices": prices,
            "watchlist": syms,
            "portfolio": port if isinstance(port, dict) else {"ok": False},
            "alerts": alert_events,
            "risk": risk,
            "signals": signal_events,
        }


stock_monitor = StockRealtimeMonitor()


def connect_to_market_data() -> str:
    """
    Preferred: native exchange WebSocket (not bundled — requires vendor URL + auth).

    Returns a short status string. **Polling** is driven by ``stock_monitor.ensure_poll_task()`` from the
    WebSocket route when clients are connected.
    """
    ws_url = (os.getenv("THIRAMAI_STOCK_MARKET_WS_URL") or "").strip()
    if ws_url:
        return f"configured_ws:{ws_url[:48]}…"
    return "polling:yfinance_nsepython_via_get_live_price"
