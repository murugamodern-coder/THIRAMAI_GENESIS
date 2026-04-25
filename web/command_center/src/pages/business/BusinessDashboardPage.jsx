import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import {
  fetchDashboardBusinessSummary,
  fetchInventoryAlerts,
  fetchInventoryList,
  fetchPendingInvoices,
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
  const [bizSummary, setBizSummary] = useState(null);
  const [invSummary, setInvSummary] = useState({ totalItems: 0, lowStockCount: 0, totalValue: 0 });
  const [pendingSummary, setPendingSummary] = useState({ count: 0, amount: 0 });
  const [stockAlerts, setStockAlerts] = useState([]);
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
      const orgId = Number(
        s?.organization_id ?? s?.org_id ?? outlet?.orgId ?? outlet?.organizationId ?? 0,
      ) || null;
      const [summaryRes, invRes, pendingRes, alertsRes] = await Promise.all([
        withTimeout(fetchDashboardBusinessSummary(orgId), "Business summary"),
        withTimeout(fetchInventoryList(), "Inventory"),
        withTimeout(fetchPendingInvoices(orgId, 200), "Pending invoices"),
        withTimeout(fetchInventoryAlerts(), "Stock alerts"),
      ]);
      if (isStale()) return;
      const safeS = s && typeof s === "object" ? s : {};
      const safeP = p && typeof p === "object" ? p : {};
      setSnap(safeS);
      setPl(safeP.ok === false ? null : safeP);
      setSubs(hint?.subsidy ? subsidyCasesList(subsidyRaw) : []);
      setBizSummary(summaryRes && typeof summaryRes === "object" ? summaryRes : {});
      const invItems = safeArray(invRes?.items ?? invRes?.inventory ?? invRes?.rows);
      const totalValue = invItems.reduce((sum, row) => {
        const qty = Number(row?.quantity ?? 0);
        const price = Number(row?.unit_price ?? row?.unit_price_pre_tax ?? 0);
        if (!Number.isFinite(qty) || !Number.isFinite(price)) return sum;
        return sum + qty * price;
      }, 0);
      setInvSummary({
        totalItems: Number(invRes?.total ?? invItems.length) || 0,
        lowStockCount: Number(invRes?.low_stock_count ?? invRes?.low_stock?.count ?? 0) || 0,
        totalValue,
      });
      const pendingInvoices = safeArray(pendingRes?.invoices);
      const pendingAmount = pendingInvoices.reduce(
        (sum, row) => sum + (Number(row?.grand_total_inr ?? 0) || 0),
        0,
      );
      setPendingSummary({
        count: Number(pendingRes?.count ?? pendingInvoices.length) || 0,
        amount: pendingAmount,
      });
      setStockAlerts(safeArray(alertsRes?.items));
    } catch (e) {
      if (isStale()) return;
      setErr(e?.response?.data?.detail || e?.message || "Load failed");
      setSnap(null);
      setPl(null);
      setSubs([]);
      setBizSummary(null);
      setInvSummary({ totalItems: 0, lowStockCount: 0, totalValue: 0 });
      setPendingSummary({ count: 0, amount: 0 });
      setStockAlerts([]);
    } finally {
      const stale = isStale();
      if (!stale) {
        setInitialLoading(false);
        setRefreshing(false);
      }
    }
  }, [hint?.subsidy, outlet?.orgId, outlet?.organizationId]);

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
  const revenueInr = useMemo(() => (bizSummary?.revenue_inr && typeof bizSummary.revenue_inr === "object" ? bizSummary.revenue_inr : {}), [bizSummary]);
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
        <h2>Business intelligence (live)</h2>
        <div className="biz-grid-2" style={{ marginTop: 8 }}>
          <div>
            <div className="cc-muted" style={{ fontSize: 12 }}>
              Revenue Today
            </div>
            <div style={{ fontWeight: 700 }}>{fmtINR(revenueInr.today)}</div>
          </div>
          <div>
            <div className="cc-muted" style={{ fontSize: 12 }}>
              This Week
            </div>
            <div style={{ fontWeight: 700 }}>{fmtINR(revenueInr.this_week)}</div>
          </div>
          <div>
            <div className="cc-muted" style={{ fontSize: 12 }}>
              This Month
            </div>
            <div style={{ fontWeight: 700 }}>{fmtINR(revenueInr.this_month)}</div>
          </div>
          <div>
            <div className="cc-muted" style={{ fontSize: 12 }}>
              Inventory Items
            </div>
            <div style={{ fontWeight: 700 }}>{invSummary.totalItems}</div>
          </div>
          <div>
            <div className="cc-muted" style={{ fontSize: 12 }}>
              Low Stock Alerts
            </div>
            <div style={{ fontWeight: 700 }}>{invSummary.lowStockCount || lowStockCount}</div>
          </div>
          <div>
            <div className="cc-muted" style={{ fontSize: 12 }}>
              Pending Invoices
            </div>
            <div style={{ fontWeight: 700 }}>
              {pendingSummary.count} ({fmtINR(pendingSummary.amount)})
            </div>
          </div>
        </div>
        <p className="cc-muted" style={{ fontSize: 12, marginTop: 8 }}>
          Inventory value: {fmtINR(invSummary.totalValue)}
        </p>
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

      <div className="cc-card">
        <h2>Stock alerts</h2>
        {stockAlerts.length === 0 ? (
          <p className="cc-muted">No low stock alerts right now.</p>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {stockAlerts.slice(0, 8).map((item, idx) => (
              <div
                key={`${item?.sku_name || "item"}-${idx}`}
                style={{
                  border: "1px solid rgba(245, 158, 11, 0.35)",
                  background: "rgba(245, 158, 11, 0.08)",
                  borderRadius: 10,
                  padding: 10,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <div>
                  <div style={{ fontWeight: 700 }}>{item?.sku_name ?? "Item"}</div>
                  <div className="cc-muted" style={{ fontSize: 12 }}>
                    Qty: {item?.quantity ?? "—"} · Reorder point: {item?.reorder_point ?? item?.threshold ?? "—"}
                  </div>
                </div>
                <button
                  type="button"
                  className="cc-btn cc-btn-secondary"
                  onClick={() => {
                    window.location.hash = "#/dashboard/inventory";
                  }}
                >
                  Reorder Now
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

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
