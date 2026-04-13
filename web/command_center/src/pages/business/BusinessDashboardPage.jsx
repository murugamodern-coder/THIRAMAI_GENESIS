import { useCallback, useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import {
  fetchBusinessPlDaily,
  fetchBusinessSnapshot,
  fetchSubsidyCases,
  postSubsidyCase,
} from "../../api/commandCenterApi.js";

function fmtINR(n) {
  const x = Number(n);
  if (Number.isNaN(x)) return "—";
  return `₹${x.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export default function BusinessDashboardPage() {
  const { base, hint } = useOutletContext();
  const [snap, setSnap] = useState(null);
  const [pl, setPl] = useState(null);
  const [subs, setSubs] = useState([]);
  const [err, setErr] = useState(null);
  const [sf, setSf] = useState({
    farmer_name: "",
    village: "",
    survey_number: "",
    scheme_name: "PM Krishi Sinchayee",
    application_status: "applied",
    subsidy_pending_inr: "",
  });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [s, p] = await Promise.all([fetchBusinessSnapshot(), fetchBusinessPlDaily()]);
      setSnap(s);
      setPl(p);
      if (hint?.subsidy) {
        const c = await fetchSubsidyCases(50);
        setSubs(c?.cases || []);
      }
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Load failed");
    }
  }, [hint?.subsidy]);

  useEffect(() => {
    load();
  }, [load]);

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
      const c = await fetchSubsidyCases(50);
      setSubs(c?.cases || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Subsidy create failed");
    }
  }

  return (
    <div>
      <h1 className="biz-page-title">Dashboard</h1>
      {err && <p className="cc-error">{err}</p>}

      <div className="cc-card">
        <h2>Today &amp; month (P&amp;L)</h2>
        {pl ? (
          <div className="biz-grid-2" style={{ marginTop: 8 }}>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                Today sales
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(pl.today?.sales_inr)}</div>
            </div>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                Today expenses
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(pl.today?.expenses_inr)}</div>
            </div>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                Today net
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(pl.today?.net_inr)}</div>
            </div>
            <div>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                MTD net
              </div>
              <div style={{ fontWeight: 700 }}>{fmtINR(pl.month_to_date?.net_inr)}</div>
            </div>
          </div>
        ) : (
          <p className="cc-muted">Loading…</p>
        )}
        <p className="cc-muted" style={{ fontSize: 12, marginTop: 8 }}>
          Sales = cash bills (timestamp) + GST invoices (invoice date). Expenses = operational categories you
          log under Spend.
        </p>
      </div>

      {snap && (
        <div className="cc-card">
          <h2>Snapshot</h2>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14 }}>
            <li>Checked in today: {snap.attendance?.checked_in_today ?? "—"}</li>
            <li>Low-stock alerts: {snap.low_stock?.length ?? 0}</li>
          </ul>
        </div>
      )}

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
          {subs.length === 0 ? (
            <p className="cc-muted">No subsidy cases yet.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 16, fontSize: 13 }}>
              {subs.slice(0, 12).map((c) => (
                <li key={c.id} style={{ marginBottom: 6 }}>
                  <strong>{c.farmer_name}</strong> — {c.scheme_name} — {c.application_status}
                  <span className="cc-muted"> · pending {fmtINR(c.subsidy_pending_inr)}</span>
                  {c.follow_up_date && (
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
