import { useCallback, useEffect, useState } from "react";

import {
  fetchStockMorningBrief,
  fetchStockPortfolio,
  fetchStockQuote,
  fetchStockSignal,
  fetchStockWatchlist,
  postStockWatchlist,
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
  const [watchlist, setWatchlist] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [signals, setSignals] = useState({});
  const [portfolio, setPortfolio] = useState(null);
  const [brief, setBrief] = useState(null);
  const [loading, setLoading] = useState(false);
  const [newSym, setNewSym] = useState("");

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

  useEffect(() => {
    refreshWatchlist();
    loadPortfolio();
    loadBrief();
  }, [refreshWatchlist, loadPortfolio, loadBrief]);

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

  const actionStyle = (action) => {
    if (action === "BUY") return { borderLeft: "4px solid #22c55e" };
    if (action === "SELL") return { borderLeft: "4px solid #ef4444" };
    return { borderLeft: "4px solid #94a3b8" };
  };

  return (
    <div className="cc-dashboard" style={{ maxWidth: 1100, margin: "0 auto", padding: "16px 20px 40px" }}>
      <h1 style={{ marginBottom: 8 }}>Stocks</h1>
      <p className="cc-muted" style={{ marginBottom: 20 }}>
        Watchlist, live quotes, rule-based signals, and paper portfolio. Not investment advice.
      </p>

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

      <Card title="Live price cards">
        {loading && watchlist.length > 0 ? <p className="cc-muted">Loading quotes…</p> : null}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: 12,
          }}
        >
          {watchlist.map((sym) => {
            const q = quotes[sym] || {};
            const last = q.last;
            return (
              <div key={sym} className="cc-card" style={{ padding: 12, margin: 0 }}>
                <div style={{ fontWeight: 700 }}>{sym}</div>
                <div style={{ fontSize: "1.4rem", marginTop: 4 }}>
                  {q.ok ? `₹${last}` : <span className="cc-muted">—</span>}
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
