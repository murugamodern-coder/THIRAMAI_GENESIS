import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteStockAlert,
  fetchAuthMe,
  fetchStockAlerts,
  fetchStockMorningBrief,
  fetchStockPortfolio,
  fetchStockQuote,
  fetchStockRealtimeStatus,
  fetchStockSignal,
  fetchStockWatchlist,
  postStockAlert,
  postStockWatchlist,
  subscribeStockRealtime,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

function Card({ title, children }) {
  return (
    <section className="cc-card" style={{ marginBottom: 20 }}>
      <h2 className="cc-today-card-title">{title}</h2>
      {children}
    </section>
  );
}

export default function StockPage() {
  const [myUserId, setMyUserId] = useState(null);
  const [watchlist, setWatchlist] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [signals, setSignals] = useState({});
  const [portfolio, setPortfolio] = useState(null);
  const [brief, setBrief] = useState(null);
  const [loading, setLoading] = useState(false);
  const [newSym, setNewSym] = useState("");
  const [rtMode, setRtMode] = useState(null);
  const [liveTick, setLiveTick] = useState(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [savedAlerts, setSavedAlerts] = useState([]);
  const [alertSymbol, setAlertSymbol] = useState("");
  const [alertCondition, setAlertCondition] = useState("above");
  const [alertPrice, setAlertPrice] = useState("");
  const [alertPct, setAlertPct] = useState("");
  const [alertAction, setAlertAction] = useState("notify");

  const refreshWatchlist = useCallback(async () => {
    try {
      const w = await fetchStockWatchlist();
      setWatchlist(Array.isArray(w?.symbols) ? w.symbols : []);
    } catch {
      setWatchlist([]);
    }
  }, []);

  const loadPortfolio = useCallback(async () => {
    try {
      const p = await fetchStockPortfolio();
      setPortfolio(p);
    } catch {
      setPortfolio(null);
    }
  }, []);

  const loadBrief = useCallback(async () => {
    try {
      const b = await fetchStockMorningBrief();
      setBrief(b);
    } catch {
      setBrief(null);
    }
  }, []);

  const loadAlerts = useCallback(async () => {
    try {
      const r = await fetchStockAlerts();
      setSavedAlerts(Array.isArray(r?.items) ? r.items : []);
    } catch {
      setSavedAlerts([]);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const me = await fetchAuthMe();
        if (me?.id != null && Number(me.id) > 0) setMyUserId(Number(me.id));
      } catch {
        setMyUserId(null);
      }
    })();
  }, []);

  useEffect(() => {
    refreshWatchlist();
    loadPortfolio();
    loadBrief();
  }, [refreshWatchlist, loadPortfolio, loadBrief]);

  useEffect(() => {
    if (!myUserId) return;
    (async () => {
      try {
        const s = await fetchStockRealtimeStatus();
        setRtMode(s?.mode || null);
      } catch {
        setRtMode(null);
      }
      loadAlerts();
    })();
  }, [myUserId, loadAlerts]);

  useEffect(() => {
    if (!myUserId) return undefined;
    setWsConnected(false);
    const disconnect = subscribeStockRealtime(myUserId, {
      onReady: () => setWsConnected(true),
      onTick: (msg) => {
        setLiveTick(msg);
        if (msg?.portfolio?.ok) setPortfolio(msg.portfolio);
      },
      onError: () => setWsConnected(false),
    });
    return () => {
      disconnect();
      setWsConnected(false);
    };
  }, [myUserId]);

  const refreshQuotesAndSignals = useCallback(async (syms) => {
    const list = Array.isArray(syms) ? syms : [];
    if (!list.length) {
      setQuotes({});
      setSignals({});
      return;
    }
    setLoading(true);
    const q = {};
    const s = {};
    try {
      await Promise.all(
        list.map(async (sym) => {
          const [pq, sg] = await Promise.all([
            fetchStockQuote(sym).catch(() => ({})),
            fetchStockSignal(sym).catch(() => ({})),
          ]);
          q[sym] = pq;
          s[sym] = sg;
        }),
      );
      setQuotes(q);
      setSignals(s);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (watchlist.length) refreshQuotesAndSignals(watchlist);
    else {
      setQuotes({});
      setSignals({});
    }
  }, [watchlist, refreshQuotesAndSignals]);

  const addSymbol = useCallback(async () => {
    const sym = newSym.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    try {
      await postStockWatchlist(sym, "NS");
      setNewSym("");
      await refreshWatchlist();
      showToastDedup({ type: "success", message: `${sym} added to watchlist` });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.message || "Failed to add" });
    } finally {
      setLoading(false);
    }
  }, [newSym, refreshWatchlist]);

  const submitAlert = useCallback(async () => {
    const sym = alertSymbol.trim().toUpperCase();
    if (!sym) {
      showToastDedup({ type: "error", message: "Symbol required" });
      return;
    }
    const body = {
      symbol: sym,
      condition: alertCondition,
      action: alertAction,
      exchange_suffix: "NS",
    };
    if (alertCondition === "percent_change") {
      const p = parseFloat(alertPct);
      if (!Number.isFinite(p) || p <= 0) {
        showToastDedup({ type: "error", message: "Percent threshold required" });
        return;
      }
      body.percent_threshold = p;
    } else {
      const px = parseFloat(alertPrice);
      if (!Number.isFinite(px) || px <= 0) {
        showToastDedup({ type: "error", message: "Price threshold required" });
        return;
      }
      body.price = px;
    }
    setLoading(true);
    try {
      await postStockAlert(body);
      setAlertSymbol("");
      setAlertPrice("");
      setAlertPct("");
      await loadAlerts();
      showToastDedup({ type: "success", message: "Alert saved" });
    } catch (e) {
      showToastDedup({ type: "error", message: e?.response?.data?.detail || e?.message || "Failed" });
    } finally {
      setLoading(false);
    }
  }, [alertSymbol, alertCondition, alertPrice, alertPct, alertAction, loadAlerts]);

  const removeAlert = useCallback(
    async (id) => {
      setLoading(true);
      try {
        await deleteStockAlert(id);
        await loadAlerts();
        showToastDedup({ type: "success", message: "Alert removed" });
      } catch (e) {
        showToastDedup({ type: "error", message: e?.message || "Failed" });
      } finally {
        setLoading(false);
      }
    },
    [loadAlerts],
  );

  const actionStyle = (action) => {
    if (action === "BUY") return { borderLeft: "4px solid #22c55e" };
    if (action === "SELL") return { borderLeft: "4px solid #ef4444" };
    return { borderLeft: "4px solid #94a3b8" };
  };

  const displayPrices = useMemo(() => {
    const p = liveTick?.prices || {};
    const merged = { ...quotes };
    Object.keys(p).forEach((k) => {
      merged[k] = { ok: true, last: p[k]?.last, cached: !!p[k]?.cached };
    });
    return merged;
  }, [liveTick, quotes]);

  return (
    <div className="cc-dashboard" style={{ maxWidth: 1100, margin: "0 auto", padding: "16px 20px 40px" }}>
      <h1 style={{ marginBottom: 8 }}>Stocks</h1>
      <p className="cc-muted" style={{ marginBottom: 20 }}>
        Live WebSocket stream, watchlist, price alerts, rule-based signals, and paper portfolio. Not investment advice.
      </p>

      <Card title="Live stream">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 8 }}>
          <span className={wsConnected ? "cc-pill" : "cc-muted"} style={{ fontSize: 13 }}>
            {wsConnected ? "WebSocket connected" : "Connecting…"}
          </span>
          {rtMode ? (
            <span className="cc-muted" style={{ fontSize: 12 }}>
              Backend: {rtMode}
            </span>
          ) : null}
          {liveTick?.as_of_utc ? (
            <span className="cc-muted" style={{ fontSize: 12 }}>
              Last tick {liveTick.as_of_utc}
            </span>
          ) : null}
        </div>
        {watchlist.length ? (
          <div
            style={{
              display: "flex",
              gap: 16,
              overflowX: "auto",
              padding: "8px 0",
              borderTop: "1px solid var(--cc-border, #333)",
              borderBottom: "1px solid var(--cc-border, #333)",
            }}
          >
            {watchlist.map((sym) => {
              const q = displayPrices[sym] || {};
              const last = q.last;
              return (
                <div key={sym} style={{ flex: "0 0 auto", minWidth: 100 }}>
                  <div style={{ fontWeight: 700 }}>{sym}</div>
                  <div style={{ fontSize: "1.25rem" }}>{q.ok && last != null ? `₹${last}` : "—"}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="cc-muted">Add symbols to populate the live ticker.</p>
        )}
        {liveTick?.risk ? (
          <div style={{ marginTop: 12, padding: 10, background: "rgba(239,68,68,0.12)", borderRadius: 8 }}>
            <strong>{liveTick.risk.title}</strong>
            <div style={{ fontSize: 14 }}>{liveTick.risk.message}</div>
          </div>
        ) : null}
        {Array.isArray(liveTick?.alerts) && liveTick.alerts.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            <strong>Price alerts (this session)</strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {liveTick.alerts.map((a, i) => (
                <li key={i} style={{ fontSize: 14 }}>
                  {a.message} <span className="cc-muted">({a.action})</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {Array.isArray(liveTick?.signals) && liveTick.signals.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            <strong>Live signals</strong>
            <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
              {liveTick.signals.map((s, i) => (
                <div key={i} className="cc-card" style={{ padding: 10, margin: 0 }}>
                  <div style={{ fontWeight: 700 }}>{s.kind}</div>
                  <div className="cc-muted" style={{ fontSize: 13 }}>
                    {s.symbol} — {s.message}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </Card>

      <Card title="Morning brief">
        {brief?.ok === false ? (
          <p className="cc-muted">{brief?.error || "Brief unavailable"}</p>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            <div>
              <strong>Sentiment:</strong> {brief?.market_sentiment || "—"}{" "}
              {brief?.nifty_change_pct != null ? `(Nifty Δ ${brief.nifty_change_pct}%)` : ""}
            </div>
            {Array.isArray(brief?.intraday_opportunities_top3) && brief.intraday_opportunities_top3.length > 0 ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {brief.intraday_opportunities_top3.map((o) => (
                  <li key={o.symbol}>
                    <strong>{o.symbol}</strong> — {o.action}: {o.reasoning}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="cc-muted">No strong intraday alignment on watchlist right now.</p>
            )}
          </div>
        )}
      </Card>

      <Card title="Watchlist">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
          {watchlist.length === 0 ? (
            <span className="cc-muted">No symbols yet — add NSE tickers (e.g. RELIANCE).</span>
          ) : (
            watchlist.map((sym) => (
              <span key={sym} className="cc-pill">
                {sym}
              </span>
            ))
          )}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            className="cc-input"
            placeholder="Symbol e.g. TCS"
            value={newSym}
            onChange={(e) => setNewSym(e.target.value)}
            style={{ maxWidth: 200 }}
          />
          <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={addSymbol}>
            Add
          </button>
        </div>
      </Card>

      <Card title="Price alerts">
        <div style={{ display: "grid", gap: 8, maxWidth: 480 }}>
          <input
            className="cc-input"
            placeholder="Symbol"
            value={alertSymbol}
            onChange={(e) => setAlertSymbol(e.target.value)}
          />
          <select className="cc-input" value={alertCondition} onChange={(e) => setAlertCondition(e.target.value)}>
            <option value="above">Above price</option>
            <option value="below">Below price</option>
            <option value="percent_change">Percent move from reference (uses live ref)</option>
          </select>
          {alertCondition === "percent_change" ? (
            <input
              className="cc-input"
              placeholder="Threshold % (e.g. 2)"
              value={alertPct}
              onChange={(e) => setAlertPct(e.target.value)}
            />
          ) : (
            <input
              className="cc-input"
              placeholder="Price ₹"
              value={alertPrice}
              onChange={(e) => setAlertPrice(e.target.value)}
            />
          )}
          <select className="cc-input" value={alertAction} onChange={(e) => setAlertAction(e.target.value)}>
            <option value="notify">Notify</option>
            <option value="suggest">Suggest</option>
            <option value="confirm_sell">Confirm sell</option>
          </select>
          <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={submitAlert}>
            Save alert
          </button>
        </div>
        {savedAlerts.length ? (
          <ul style={{ marginTop: 16, paddingLeft: 18 }}>
            {savedAlerts.map((a) => (
              <li key={a.id} style={{ marginBottom: 8, fontSize: 14 }}>
                <strong>{a.symbol}</strong> — {a.condition}{" "}
                {a.price_threshold != null ? `₹${a.price_threshold}` : ""}
                {a.percent_threshold != null ? `${a.percent_threshold}% vs ref` : ""}{" "}
                <button type="button" className="cc-btn cc-btn-secondary" disabled={loading} onClick={() => removeAlert(a.id)}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="cc-muted" style={{ marginTop: 12 }}>
            No saved alerts.
          </p>
        )}
      </Card>

      <Card title="Live price cards (HTTP fallback)">
        {loading && watchlist.length > 0 ? <p className="cc-muted">Loading quotes…</p> : null}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: 12,
          }}
        >
          {watchlist.map((sym) => {
            const q = displayPrices[sym] || {};
            const last = q.last;
            return (
              <div key={sym} className="cc-card" style={{ padding: 12, margin: 0 }}>
                <div style={{ fontWeight: 700 }}>{sym}</div>
                <div style={{ fontSize: "1.4rem", marginTop: 4 }}>
                  {q.ok && last != null ? `₹${last}` : <span className="cc-muted">—</span>}
                </div>
                {q.cached ? <div className="cc-muted" style={{ fontSize: 12 }}>cached quote</div> : null}
              </div>
            );
          })}
        </div>
      </Card>

      <Card title="Signal cards">
        <div style={{ display: "grid", gap: 12 }}>
          {watchlist.map((sym) => {
            const sg = signals[sym] || {};
            const act = sg.action || "—";
            return (
              <div key={sym} className="cc-card" style={{ padding: 12, margin: 0, ...actionStyle(act) }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <strong>{sym}</strong>
                  <span style={{ fontWeight: 800 }}>{act}</span>
                </div>
                {sg.risk_blocked ? <div className="cc-muted">Risk cap active — HOLD.</div> : null}
                <div className="cc-muted" style={{ fontSize: 13, marginTop: 6 }}>
                  {sg.reasoning || sg.error || ""}
                </div>
                {sg.entry_price != null ? (
                  <div style={{ fontSize: 13, marginTop: 6 }}>
                    Entry {sg.entry_price} · Tgt {sg.target_price} · SL {sg.stop_loss} · R:R {sg.risk_reward}
                  </div>
                ) : null}
              </div>
            );
          })}
          {!watchlist.length ? <p className="cc-muted">Add symbols to see signals.</p> : null}
        </div>
      </Card>

      <Card title="Portfolio summary">
        {!portfolio?.ok ? (
          <p className="cc-muted">{portfolio?.error || "Load portfolio to see P&amp;L."}</p>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            <div>
              <strong>Total value:</strong> ₹{portfolio.total_current_value_inr} · <strong>Total P&amp;L:</strong>{" "}
              ₹{portfolio.total_pnl_inr}
            </div>
            {portfolio.risk_blocked ? (
              <div style={{ color: "#b45309" }}>Daily loss limit reached — signals disabled.</div>
            ) : null}
            <div style={{ fontSize: 13 }} className="cc-muted">
              Realized today: ₹{portfolio.daily_realized_pnl_inr} (max loss ₹{portfolio.max_daily_loss_inr})
            </div>
            <table className="cc-table" style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Symbol</th>
                  <th>Qty</th>
                  <th>Avg</th>
                  <th>Last</th>
                  <th>P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {(portfolio.positions || []).map((row) => (
                  <tr key={row.symbol}>
                    <td>{row.symbol}</td>
                    <td>{row.quantity}</td>
                    <td>{row.avg_buy_price_inr}</td>
                    <td>{row.last_price_inr ?? "—"}</td>
                    <td>{row.pnl_inr}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!portfolio.positions?.length ? <p className="cc-muted">No open positions.</p> : null}
          </div>
        )}
      </Card>
    </div>
  );
}
