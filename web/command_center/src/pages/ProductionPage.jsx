import { useCallback, useEffect, useState } from "react";

import {
  createMaintenanceLog,
  fetchProductionMachines,
  fetchProductionSummary,
} from "../api/commandCenterApi.js";

export default function ProductionPage() {
  const [summary, setSummary] = useState(null);
  const [machines, setMachines] = useState([]);
  const [err, setErr] = useState(null);
  const [maint, setMaint] = useState({
    equipment_id: "",
    issue_description: "",
    cost: "0",
    technician_name: "",
  });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [s, m] = await Promise.all([fetchProductionSummary(), fetchProductionMachines()]);
      setSummary(s?.ok ? s : null);
      setMachines(m?.machines || []);
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : e?.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function submitMaint(e) {
    e.preventDefault();
    setErr(null);
    try {
      await createMaintenanceLog({
        equipment_id: Number(maint.equipment_id),
        issue_description: maint.issue_description.trim(),
        cost: Number(maint.cost) || 0,
        technician_name: maint.technician_name.trim() || null,
      });
      setMaint({ equipment_id: "", issue_description: "", cost: "0", technician_name: "" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : "Maintenance log failed");
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 16px" }}>Production</h1>
      {err && <p className="cc-error">{err}</p>}

      <div className="cc-card">
        <h2>Summary (all-time unless API gains date filters)</h2>
        {summary ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
            <div className="cc-kpi">
              <div className="label">Logs</div>
              <div className="value">{summary.log_count}</div>
            </div>
            <div className="cc-kpi">
              <div className="label">Yield out</div>
              <div className="value">{summary.total_yield_out}</div>
            </div>
            <div className="cc-kpi">
              <div className="label">Blocks out</div>
              <div className="value">{summary.total_blocks_out}</div>
            </div>
            <div className="cc-kpi">
              <div className="label">Labor INR</div>
              <div className="value">{summary.total_labor_cost_inr}</div>
            </div>
          </div>
        ) : (
          <p className="cc-muted">No summary.</p>
        )}
      </div>

      <div className="cc-card">
        <h2>Log maintenance</h2>
        <form onSubmit={submitMaint} style={{ display: "grid", gap: 8, maxWidth: 520 }}>
          <select
            className="cc-select"
            value={maint.equipment_id}
            onChange={(e) => setMaint((m) => ({ ...m, equipment_id: e.target.value }))}
            required
          >
            <option value="">Equipment…</option>
            {machines.map((eq) => (
              <option key={eq.id} value={eq.id}>
                {eq.name} (id {eq.id})
              </option>
            ))}
          </select>
          <textarea
            className="cc-textarea"
            style={{ minHeight: 72 }}
            placeholder="Issue description"
            value={maint.issue_description}
            onChange={(e) => setMaint((m) => ({ ...m, issue_description: e.target.value }))}
            required
          />
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Cost INR"
              value={maint.cost}
              onChange={(e) => setMaint((m) => ({ ...m, cost: e.target.value }))}
            />
            <input
              className="cc-input"
              placeholder="Technician"
              value={maint.technician_name}
              onChange={(e) => setMaint((m) => ({ ...m, technician_name: e.target.value }))}
            />
          </div>
          <button type="submit" className="cc-btn cc-btn-primary" style={{ width: 180 }}>
            Submit maintenance
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Machine status</h2>
        <div className="cc-table-wrap">
          <table className="cc-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Model</th>
                <th>Status</th>
                <th>Next service</th>
              </tr>
            </thead>
            <tbody>
              {machines.map((eq) => (
                <tr key={eq.id}>
                  <td>{eq.id}</td>
                  <td>{eq.name}</td>
                  <td>{eq.model || "—"}</td>
                  <td>{eq.status || "—"}</td>
                  <td>{eq.next_service_due || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
