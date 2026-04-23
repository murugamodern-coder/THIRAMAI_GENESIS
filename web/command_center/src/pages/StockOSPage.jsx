import { useCallback, useEffect, useMemo, useState } from "react";

import {
  fetchStockAlerts,
  fetchStockMorningBrief,
  fetchStockPortfolio,
  fetchStockQuote,
  fetchStockWatchlist,
  postStockAlert,
  postStockWatchlist,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

function formatInr(val) {
  const n = Number(val);
  if (!Number.isFinite(n)) return "—";
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** NSE cash session Mon–Fri 09:15–15:30 IST (approx; excludes holidays). */
function nseSessionBadge() {
  try {
    const tz = "Asia/Kolkata";
    const now = new Date();
    const wd = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: tz }).format(now);
    if (wd === "Sat" || wd === "Sun") {
      return { label: "Market closed (weekend)", variant: "muted", open: false };
    }
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(now);
    const hh = Number(parts.find((p) => p.type === "hour")?.value ?? 0);
    const mm = Number(parts.find((p) => p.type === "minute")?.value ?? 0);
    const mins = hh * 60 + mm;
    const openM = 9 * 60 + 15;
    const closeM = 15 * 60 + 30;
    const open = mins >= openM && mins <= closeM;
    return open
      ? { label: "NSE session live (IST)", variant: "live", open: true }
      : { label: "NSE session closed (IST)", variant: "muted", open: false };
  } catch {
    return { label: "IST schedule unknown", variant: "muted", open: false };
  }
}

function SkeletonBlock({ h = 120 }) {
  return <div className="ui-skeleton" style={{ height: h, borderRadius: 12 }} aria-hidden />;
}

function ConnectBrokerCard({ detail }) {
  return (
    <div className="cc-card" style={{ borderLeft: "4px solid #E24B4A", marginBottom: 24 }}>
      <h2 className="cc-section-title" style={{ marginTop: 0 }}>
        Connect market data
      </h2>
      <p className="cc-muted" style={{ marginBottom: 12 }}>
        Stock OS uses Thiramai&apos;s paper portfolio and watchlist stored in your account database. Live quotes come from the
        server (<strong>yfinance</strong> / optional <strong>nsepython</strong>). Nothing here replaces your broker.
      </p>
      {detail ? (
        <p className="cc-error" style={{ marginBottom: 12 }}>
          {detail}
        </p>
      ) : null}
      <ol style={{ margin: "0 0 0 18px", padding: 0, fontSize: 14, lineHeight: 1.6 }}>
        <li>
          Sign in — endpoints require a valid JWT (same session as the rest of the Command Center).
        </li>
        <li>
          Ensure the API has <strong>DATABASE_URL</strong> set so watchlist, portfolio, and alerts persist.
        </li>
        <li>
          Install <strong>yfinance</strong> on the API host for quotes; optionally <strong>nsepython</strong> as a fallback for NSE cash.
        </li>
        <li>
          For live broker execution (outside this page), configure broker credentials and env vars documented in{' '}
          <code>services/broker/</code> — paper trades use <strong>POST /stocks/assistant/portfolio/buy</strong>.
        </li>
      </ol>
    </div>
  );
}

export default function StockOSPage() {
  const session = useMemo(() => nseSessionBadge(), []);
  const [loading, setLoading] = useState(true);
  const [fatalError, setFatalError] = useState(null);

  const [symbols, setSymbols] = useState([]);
  const [quotesBySymbol, setQuotesBySymbol] = useState({});
  const [wlError, setWlError] = useState(null);

  const [portfolio, setPortfolio] = useState(null);
  const [pfError, setPfError] = useState(null);

  const [brief, setBrief] = useState(null);
  const [briefOpen, setBriefOpen] = useState(true);
  const [briefError, setBriefError] = useState(null);

  const [alerts, setAlerts] = useState([]);
  const [alError, setAlError] = useState(null);

  const [newSymbol, setNewSymbol] = useState("");
  const [addBusy, setAddBusy] = useState(false);

  const [alertSymbol, setAlertSymbol] = useState("");
  const [alertCond, setAlertCond] = useState("above");
  const [alertPrice, setAlertPrice] = useState("");
  const [alertPct, setAlertPct] = useState("");
  const [alertBusy, setAlertBusy] = useState(false);

  const load = useCallback(async () => {
    setFatalError(null);
    setWlError(null);
    setPfError(null);
    setBriefError(null);
    setAlError(null);

    let wlData = null;
    let pfData = null;
    let briefData = null;
    let alData = null;

    try {
      const [w, p, b, a] = await Promise.all([
        fetchStockWatchlist().catch((e) => {
          setWlError(e?.response?.data?.detail || e?.message || "Watchlist failed");
          return null;
        }),
        fetchStockPortfolio().catch((e) => {
          setPfError(e?.response?.data?.detail || e?.message || "Portfolio failed");
          return null;
        }),
        fetchStockMorningBrief().catch((e) => {
          setBriefError(e?.response?.data?.detail || e?.message || "Morning brief failed");
          return null;
        }),
        fetchStockAlerts().catch((e) => {
          setAlError(e?.response?.data?.detail || e?.message || "Alerts failed");
          return null;
        }),
      ]);
      wlData = w;
      pfData = p;
      briefData = b;
      alData = a;
    } catch (e) {
      setFatalError(e?.response?.data?.detail || e?.message || "Could not reach Stock APIs");
      setLoading(false);
      return;
    }

    const syms = Array.isArray(wlData?.symbols) ? wlData.symbols : [];
    setSymbols(syms);

    const quoteEntries = await Promise.all(
      syms.map(async (sym) => {
        const key = String(sym || "").trim().toUpperCase();
        if (!key) return null;
        try {
          const q = await fetchStockQuote(key);
          return [key, q];
        } catch {
          return [key, { ok: false }];
        }
      }),
    );
    const qb = {};
    quoteEntries.forEach((row) => {
      if (row) qb[row[0]] = row[1];
    });
    setQuotesBySymbol(qb);

    setPortfolio(pfData && pfData.ok === false ? null : pfData);
    if (pfData && pfData.ok === false) setPfError(pfData.error || "Portfolio unavailable");

    setBrief(briefData && briefData.ok === false ? null : briefData);
    if (briefData && briefData.ok === false) setBriefError(briefData.error || "Brief unavailable");

    const items = Array.isArray(alData?.items) ? alData.items : [];
    setAlerts(items);

    setLoading(false);
  }, []);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  useEffect(() => {
    const id = window.setInterval(() => {
      load().catch(() => {});
    }, 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function onAddSymbol(e) {
    e.preventDefault();
    const raw = newSymbol.trim().toUpperCase();
    if (!raw || addBusy) return;
    setAddBusy(true);
    try {
      const out = await postStockWatchlist(raw, "NS");
      if (!out?.ok) {
        showToastDedup({ type: "error", message: out?.error || "Could not add symbol" });
      } else {
        showToastDedup({ type: "success", message: `${raw} added to watchlist` });
        setNewSymbol("");
        await load();
      }
    } catch (err) {
      showToastDedup({ type: "error", message: err?.response?.data?.detail || err?.message || "Add failed" });
    } finally {
      setAddBusy(false);
    }
  }

  async function onCreateAlert(e) {
    e.preventDefault();
    const sym = alertSymbol.trim().toUpperCase();
    if (!sym || alertBusy) return;
    setAlertBusy(true);
    try {
      const payload = {
        symbol: sym,
        condition: alertCond,
        action: "notify",
        exchange_suffix: "NS",
      };
      if (alertCond === "percent_change") {
        payload.percent_threshold = alertPct.trim() || null;
      } else {
        payload.price = alertPrice.trim() ? Number(alertPrice) : null;
      }
      await postStockAlert(payload);
      showToastDedup({ type: "success", message: "Alert created" });
      setAlertSymbol("");
      setAlertPrice("");
      setAlertPct("");
      await load();
    } catch (err) {
      showToastDedup({ type: "error", message: err?.response?.data?.detail || err?.message || "Alert failed" });
    } finally {
      setAlertBusy(false);
    }
  }

  function dispatchCommand(cmd) {
    window.dispatchEvent(new CustomEvent("thiramai-command-request", { detail: { command: cmd, source: "stock_os" } }));
  }

  const portfolioPositions = Array.isArray(portfolio?.positions) ? portfolio.positions : [];
  const totalVal = portfolio?.total_current_value_inr;
  const totalPnl = portfolio?.total_pnl_inr;
  const dayRealized = portfolio?.daily_realized_pnl_inr;

  /** Broad failure: auth/DB/network — show setup card (not for single-panel errors). */
  const showRecoveryCard = Boolean(fatalError) || (!loading && Boolean(wlError) && Boolean(pfError));

  return (
    <div className="stock-os-page">
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 20 }}>
        <div>
          <h1 className="cc-page-title" style={{ marginBottom: 4 }}>
            📈 Stock OS — Market Intelligence
          </h1>
          <p className="cc-muted" style={{ margin: 0 }}>Paper portfolio, watchlist, and alerts — refreshed every 60s.</p>
        </div>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            fontSize: 13,
            fontWeight: 600,
            padding: "8px 12px",
            borderRadius: 999,
            background: session.open ? "rgba(16,185,129,0.15)" : "rgba(148,163,184,0.15)",
            color: session.open ? "#10b981" : "var(--cc-muted)",
          }}
        >
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: session.open ? "#10b981" : "#94a3b8" }} />
          {session.label}
        </span>
      </div>

      {showRecoveryCard ? <ConnectBrokerCard detail={fatalError || wlError} /> : null}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
        {/* Watchlist */}
        <section className="cc-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <h2 className="cc-section-title" style={{ margin: 0 }}>Watchlist</h2>
            <span className="cc-muted" style={{ fontSize: 12 }}>{symbols.length} symbols</span>
          </div>
          {loading ? (
            <SkeletonBlock h={160} />
          ) : wlError ? (
            <p className="cc-error">{wlError}</p>
          ) : symbols.length === 0 ? (
            <p className="cc-muted">No symbols yet. Add an NSE ticker (e.g. RELIANCE).</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="cc-table" style={{ width: "100%", fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Symbol</th>
                    <th style={{ textAlign: "right" }}>LTP</th>
                    <th style={{ textAlign: "right" }}>Δ%</th>
                    <th style={{ textAlign: "right" }}>Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.map((sym) => {
                    const q = quotesBySymbol[String(sym).toUpperCase()] || {};
                    const last = q.last != null ? Number(q.last) : null;
                    const chgPct = q.change_pct != null ? Number(q.change_pct) : null;
                    const chgAmt = q.change_amount != null ? Number(q.change_amount) : null;
                    const pos = chgPct != null && chgPct >= 0;
                    const neg = chgPct != null && chgPct < 0;
                    const color = pos ? "#10b981" : neg ? "#ef4444" : "var(--cc-muted)";
                    return (
                      <tr key={sym}>
                        <td style={{ fontWeight: 700 }}>{sym}</td>
                        <td style={{ textAlign: "right" }}>{last != null && Number.isFinite(last) ? formatInr(last) : "—"}</td>
                        <td style={{ textAlign: "right", color, fontWeight: 600 }}>
                          {chgPct != null && Number.isFinite(chgPct) ? `${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%` : "—"}
                        </td>
                        <td style={{ textAlign: "right", color }}>
                          {chgAmt != null && Number.isFinite(chgAmt) ? `${chgAmt >= 0 ? "+" : ""}${chgAmt.toFixed(2)}` : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <form onSubmit={onAddSymbol} style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
            <input
              className="cc-input"
              placeholder="Add symbol (e.g. TCS)"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
              style={{ flex: "1 1 140px", minWidth: 120 }}
            />
            <button type="submit" className="cc-btn cc-btn-primary" disabled={addBusy}>
              {addBusy ? "Adding…" : "Add stock"}
            </button>
          </form>
        </section>

        {/* Portfolio */}
        <section className="cc-card">
          <h2 className="cc-section-title" style={{ marginTop: 0 }}>Portfolio (paper)</h2>
          {loading ? (
            <SkeletonBlock h={160} />
          ) : pfError ? (
            <p className="cc-error">{pfError}</p>
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, marginBottom: 14 }}>
                <div className="cc-kpi" style={{ margin: 0, padding: 10 }}>
                  <div className="cc-muted" style={{ fontSize: 11 }}>Total value</div>
                  <div style={{ fontWeight: 700 }}>{formatInr(totalVal)}</div>
                </div>
                <div className="cc-kpi" style={{ margin: 0, padding: 10 }}>
                  <div className="cc-muted" style={{ fontSize: 11 }}>MTM P&amp;L</div>
                  <div style={{ fontWeight: 700, color: Number(totalPnl) >= 0 ? "#10b981" : "#ef4444" }}>
                    {formatInr(totalPnl)}
                  </div>
                </div>
                <div className="cc-kpi" style={{ margin: 0, padding: 10 }}>
                  <div className="cc-muted" style={{ fontSize: 11 }}>Today realized</div>
                  <div style={{ fontWeight: 700, color: Number(dayRealized) >= 0 ? "#10b981" : "#ef4444" }}>
                    {formatInr(dayRealized)}
                  </div>
                </div>
              </div>
              {portfolio?.risk_blocked ? (
                <p className="cc-error" style={{ fontSize: 13 }}>Daily equity loss guard active — signals may be limited.</p>
              ) : null}
              {portfolioPositions.length === 0 ? (
                <p className="cc-muted">No open positions. Use API paper buy or Jarvis tools to open trades.</p>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table className="cc-table" style={{ width: "100%", fontSize: 13 }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: "left" }}>Symbol</th>
                        <th style={{ textAlign: "right" }}>Qty</th>
                        <th style={{ textAlign: "right" }}>Avg</th>
                        <th style={{ textAlign: "right" }}>Last</th>
                        <th style={{ textAlign: "right" }}>P&amp;L %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolioPositions.map((row) => {
                        const cost = Number(row.cost_basis_inr);
                        const pnl = Number(row.pnl_inr);
                        const pct = cost > 0 ? (pnl / cost) * 100 : null;
                        const lp = row.last_price_inr != null ? Number(row.last_price_inr) : null;
                        return (
                          <tr key={`${row.symbol}-${row.exchange_suffix}`}>
                            <td style={{ fontWeight: 700 }}>{row.symbol}</td>
                            <td style={{ textAlign: "right" }}>{row.quantity ?? "—"}</td>
                            <td style={{ textAlign: "right" }}>{formatInr(row.avg_buy_price_inr)}</td>
                            <td style={{ textAlign: "right" }}>
                              {lp != null && Number.isFinite(lp) ? formatInr(lp) : "—"}
                              {!row.quote_ok ? (
                                <span className="cc-muted" style={{ fontSize: 10, marginLeft: 4 }}>(stale)</span>
                              ) : null}
                            </td>
                            <td style={{ textAlign: "right", fontWeight: 600, color: (pct ?? 0) >= 0 ? "#10b981" : "#ef4444" }}>
                              {pct != null && Number.isFinite(pct) ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {/* Morning brief */}
      <section className="cc-card" style={{ marginTop: 16 }}>
        <button
          type="button"
          onClick={() => setBriefOpen((v) => !v)}
          className="cb-morning-brief__toggle"
          style={{
            display: "flex",
            width: "100%",
            justifyContent: "space-between",
            alignItems: "center",
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 0,
            font: "inherit",
          }}
          aria-expanded={briefOpen}
        >
          <h2 className="cc-section-title" style={{ margin: 0 }}>Morning brief</h2>
          <span className="cc-muted">{briefOpen ? "▼" : "▶"}</span>
        </button>
        {loading ? (
          <SkeletonBlock h={100} />
        ) : briefError ? (
          <p className="cc-error">{briefError}</p>
        ) : briefOpen && brief ? (
          <div style={{ marginTop: 12 }}>
            <p style={{ marginTop: 0, fontSize: 14, lineHeight: 1.5 }}>
              <strong>Sentiment:</strong> {brief.market_sentiment || "—"}
              {brief.nifty_change_pct != null ? (
                <span className="cc-muted">
                  {" "}
                  (Nifty doD: {Number(brief.nifty_change_pct) >= 0 ? "+" : ""}
                  {Number(brief.nifty_change_pct).toFixed(2)}%)
                </span>
              ) : null}
            </p>
            {brief.nifty?.ok ? (
              <p className="cc-muted" style={{ fontSize: 13 }}>
                Nifty spot ≈ {formatInr(brief.nifty.last)} ({brief.nifty.change_pct >= 0 ? "+" : ""}
                {brief.nifty.change_pct}% doD)
              </p>
            ) : null}
            {brief.sensex?.ok ? (
              <p className="cc-muted" style={{ fontSize: 13 }}>
                Sensex ≈ {formatInr(brief.sensex.last)} ({brief.sensex.change_pct >= 0 ? "+" : ""}
                {brief.sensex.change_pct}% doD)
              </p>
            ) : null}
            {Array.isArray(brief.intraday_opportunities_top3) && brief.intraday_opportunities_top3.length > 0 ? (
              <div style={{ marginTop: 10 }}>
                <div className="cc-muted" style={{ fontSize: 12, marginBottom: 6 }}>Top signals</div>
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {brief.intraday_opportunities_top3.map((o) => (
                    <li key={o.symbol} style={{ marginBottom: 6 }}>
                      <strong>{o.symbol}</strong> — {o.action}{" "}
                      {o.reasoning ? <span className="cc-muted">({o.reasoning})</span> : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="cc-muted" style={{ fontSize: 11, marginTop: 12 }}>
              {brief.disclaimer || brief.hint || "Not investment advice; verify with your broker."}
            </p>
          </div>
        ) : null}
      </section>

      {/* Alerts */}
      <section className="cc-card" style={{ marginTop: 16 }}>
        <h2 className="cc-section-title" style={{ marginTop: 0 }}>Price alerts</h2>
        {loading ? (
          <SkeletonBlock h={80} />
        ) : alError ? (
          <p className="cc-error">{alError}</p>
        ) : alerts.length === 0 ? (
          <p className="cc-muted">No active alerts.</p>
        ) : (
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
            {alerts.map((a) => (
              <li key={a.id} style={{ marginBottom: 8 }}>
                <strong>{a.symbol}</strong> — {a.condition}{" "}
                {a.price_threshold != null ? `@ ${a.price_threshold}` : ""}
                {a.percent_threshold != null ? `${a.percent_threshold}% (from ref)` : ""}
                <span className="cc-muted" style={{ fontSize: 12 }}> · {a.action}</span>
              </li>
            ))}
          </ul>
        )}
        <form onSubmit={onCreateAlert} style={{ display: "grid", gap: 10, marginTop: 14, maxWidth: 480 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>Add alert</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <input className="cc-input" placeholder="Symbol" value={alertSymbol} onChange={(e) => setAlertSymbol(e.target.value.toUpperCase())} />
            <select className="cc-input" value={alertCond} onChange={(e) => setAlertCond(e.target.value)} style={{ minWidth: 140 }}>
              <option value="above">above price</option>
              <option value="below">below price</option>
              <option value="percent_change">percent move</option>
            </select>
          </div>
          {alertCond === "percent_change" ? (
            <input className="cc-input" placeholder="Threshold % (e.g. 2.5)" value={alertPct} onChange={(e) => setAlertPct(e.target.value)} />
          ) : (
            <input className="cc-input" placeholder="Price (INR)" value={alertPrice} onChange={(e) => setAlertPrice(e.target.value)} />
          )}
          <button type="submit" className="cc-btn cc-btn-primary" style={{ alignSelf: "flex-start" }} disabled={alertBusy}>
            {alertBusy ? "Saving…" : "Add alert"}
          </button>
        </form>
      </section>

      {/* Quick actions */}
      <section className="cc-card" style={{ marginTop: 16 }}>
        <h2 className="cc-section-title" style={{ marginTop: 0 }}>Quick actions</h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          <button type="button" className="cc-btn cc-btn-ghost" onClick={() => dispatchCommand("analyze RELIANCE")}>
            🔍 Analyze stock
          </button>
          <button type="button" className="cc-btn cc-btn-ghost" onClick={() => dispatchCommand("portfolio report")}>
            📊 Portfolio report
          </button>
        </div>
        <p className="cc-muted" style={{ fontSize: 12, marginTop: 10 }}>
          Sends a command to the global command bar (same flow as Central Brain suggestions).
        </p>
      </section>
    </div>
  );
}
