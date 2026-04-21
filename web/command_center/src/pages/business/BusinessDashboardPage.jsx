import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import {
  fetchBusinessPlDaily,
  fetchBusinessSnapshot,
  fetchSubsidyCases,
  postSubsidyCase,
} from "../../api/commandCenterApi.js";
import { safeArray } from "../../lib/safeData.js";

function fmtINR(n) {
  const x = Number(n);
  if (Number.isNaN(x)) return "—";
  return `₹${x.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

/** Normalize subsidy list from API (must always be an array for .slice/.map). */
function subsidyCasesList(raw) {
  const c = raw?.cases ?? raw?.items ?? raw;
  return Array.isArray(c) ? c : [];
}

function withTimeout(task, label, timeoutMs = 9000) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
    task
      .then((value) => {
        window.clearTimeout(timer);
        resolve(value);
      })
      .catch((error) => {
        window.clearTimeout(timer);
        reject(error);
      });
  });
}

export default function BusinessDashboardPage() {
  const outlet = useOutletContext();
  const base = outlet?.base ?? "";
  const hint = outlet?.hint ?? null;

  const [snap, setSnap] = useState(null);
  const [pl, setPl] = useState(null);
  const [subs, setSubs] = useState([]);
  const [err, setErr] = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sf, setSf] = useState({
    farmer_name: "",
    village: "",
    survey_number: "",
    scheme_name: "PM Krishi Sinchayee",
    application_status: "applied",
    subsidy_pending_inr: "",
  });
  const requestIdRef = useRef(0);

  const load = useCallback(async ({ background = false } = {}) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setErr(null);
    if (background) setRefreshing(true);
    else setInitialLoading(true);

    const isStale = () => requestId !== requestIdRef.current;
    try {
      const [s, p, subsidyRaw] = await Promise.all([
        withTimeout(fetchBusinessSnapshot(), "Business snapshot"),
        withTimeout(fetchBusinessPlDaily(), "Business P&L"),
        hint?.subsidy ? withTimeout(fetchSubsidyCases(50), "Subsidy list") : Promise.resolve([]),
      ]);
      if (isStale()) return;
      const safeS = s && typeof s === "object" ? s : {};
      const safeP = p && typeof p === "object" ? p : {};
      setSnap(safeS);
      setPl(safeP.ok === false ? null : safeP);
      setSubs(hint?.subsidy ? subsidyCasesList(subsidyRaw) : []);
    } catch (e) {
      if (isStale()) return;
      setErr(e?.response?.data?.detail || e?.message || "Load failed");
      setSnap(null);
      setPl(null);
      setSubs([]);
    } finally {
      const stale = isStale();
      if (!stale) {
        setInitialLoading(false);
        setRefreshing(false);
      }
    }
  }, [hint?.subsidy]);

  useEffect(() => {
    load();
    return () => {
      requestIdRef.current += 1;
    };
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      load({ background: true });
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const subsRows = useMemo(() => safeArray(subs), [subs]);

  const plSafe = useMemo(() => (pl && typeof pl === "object" ? pl : {}), [pl]);
  const today = useMemo(
    () => (plSafe.today && typeof plSafe.today === "object" ? plSafe.today : {}),
    [plSafe],
  );
  const mtd = useMemo(
    () => (plSafe.month_to_date && typeof plSafe.month_to_date === "object" ? plSafe.month_to_date : {}),
    [plSafe],
  );

  const snapSafe = useMemo(() => (snap && typeof snap === "object" ? snap : null), [snap]);
  const lowStockCount = useMemo(() => {
    const lowStockRaw = snapSafe?.low_stock_alerts ?? snapSafe?.low_stock;
    return Array.isArray(lowStockRaw)
      ? lowStockRaw.length
      : Number(lowStockRaw?.length ?? lowStockRaw?.count ?? 0) || 0;
  }, [snapSafe]);
  const checkedIn = useMemo(
    () =>
      snapSafe?.attendance_today?.checked_in_today ??
      snapSafe?.attendance_today?.checked_in ??
      snapSafe?.attendance?.checked_in_today ??
      "—",
    [snapSafe],
  );

  async function addSubsidy(e) {
    e.preventDefault();
    setErr(null);
    try {
      await postSubsidyCase({
        farmer_name: sf.farmer_name.trim(),
        village: sf.village.trim(),
        survey_number: sf.survey_number.trim(),
        scheme_name: sf.scheme_name.trim(),
        application_status: sf.application_status,
        subsidy_pending_inr: sf.subsidy_pending_inr || "0",
        subsidy_received_inr: "0",
      });
      setSf((f) => ({ ...f, farmer_name: "", survey_number: "", subsidy_pending_inr: "" }));
      await load({ background: true });
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Subsidy create failed");
    }
  }

  if (initialLoading) {
    return (
      <div>
        <h1 className="biz-page-title">Dashboard</h1>
        <p className="cc-muted">Loading Business OS...</p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="biz-page-title">Dashboard</h1>
      {err && <p className="cc-error">{err}</p>}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <button type="button" className="cc-btn cc-btn-secondary" onClick={() => load({ background: true })}>
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div className="cc-card">
        <h2>Today &amp; month (P&amp;L)</h2>
        {pl && pl.ok !== false ? (
          <div className="biz-grid-2" style={{ marginTop: 8 }}>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                Today sales
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(today.sales_inr)}</div>
            </div>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                Today expenses
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(today.expenses_inr)}</div>
            </div>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                Today net
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(today.net_inr)}</div>
            </div>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                MTD net
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(mtd.net_inr)}</div>
            </div>
          </div>
        ) : (
          <p className="cc-muted">No P&amp;L data (API unavailable or not configured).</p>
        )}
        <p className="cc-muted" style={{ fontSize: 12, marginTop: 8 }}>
          Sales = cash bills (timestamp) + GST invoices (invoice date). Expenses = operational categories you
          log under Spend.
        </p>
      </div>

      {snapSafe ? (
        <div className="cc-card">
          <h2>Snapshot</h2>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
            <li>Checked in today: {checkedIn ?? "—"}</li>
            <li>Low-stock alerts: {lowStockCount}</li>
          </ul>
        </div>
      ) : null}

      {hint?.subsidy && (
        <div className="cc-card">
          <h2>Subsidy tracking</h2>
          <form onSubmit={addSubsidy} style={{ display: "grid", gap: 8, marginBottom: 12 }}>
            <input
              className="cc-input"
              placeholder="Farmer name"
              value={sf.farmer_name}
              onChange={(e) => setSf((f) => ({ ...f, farmer_name: e.target.value }))}
              required
            />
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="cc-input"
                placeholder="Village"
                value={sf.village}
                onChange={(e) => setSf((f) => ({ ...f, village: e.target.value }))}
              />
              <input
                className="cc-input"
                placeholder="Survey no."
                value={sf.survey_number}
                onChange={(e) => setSf((f) => ({ ...f, survey_number: e.target.value }))}
              />
            </div>
            <input
              className="cc-input"
              placeholder="Scheme"
              value={sf.scheme_name}
              onChange={(e) => setSf((f) => ({ ...f, scheme_name: e.target.value }))}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <select
                className="cc-select"
                value={sf.application_status}
                onChange={(e) => setSf((f) => ({ ...f, application_status: e.target.value }))}
              >
                <option value="draft">draft</option>
                <option value="applied">applied</option>
                <option value="approved">approved</option>
                <option value="disbursed">disbursed</option>
                <option value="rejected">rejected</option>
              </select>
              <input
                className="cc-input"
                type="number"
                placeholder="Pending ₹"
                value={sf.subsidy_pending_inr}
                onChange={(e) => setSf((f) => ({ ...f, subsidy_pending_inr: e.target.value }))}
              />
            </div>
            <button type="submit" className="cc-btn cc-btn-primary" style={{ width: "100%" }}>
              Add case
            </button>
          </form>
          {subsRows.length === 0 ? (
            <p className="cc-muted">No subsidy cases yet.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13 }}>
              {subsRows.slice(0, 12).map((c) => (
                <li key={c?.id ?? String(c?.farmer_name)} style={{ marginBottom: 6 }}>
                  <strong>{c?.farmer_name ?? "—"}</strong> — {c?.scheme_name ?? "—"} — {c?.application_status ?? "—"}
                  <span className="cc-muted"> · pending {fmtINR(c?.subsidy_pending_inr)}</span>
                  {c?.follow_up_date && (
                    <span className="cc-muted"> · follow-up {c.follow_up_date}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="cc-muted" style={{ fontSize: 13 }}>
        <Link to={`${base}/inventory`}>Stock</Link>
        {" · "}
        <Link to={`${base}/billing`}>Bills</Link>
        {" · "}
        <Link to={`${base}/tasks`}>Tasks &amp; checklists</Link>
      </p>
    </div>
  );
}
