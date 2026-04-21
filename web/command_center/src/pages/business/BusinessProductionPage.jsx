import { useCallback, useEffect, useState } from "react";

import {
  createMaintenanceLog,
  fetchProductionAssets,
  fetchProductionMachines,
  fetchProductionSummary,
} from "../../api/commandCenterApi.js";
import api from "../../api/client.js";

export default function BusinessProductionPage() {
  const [summary, setSummary] = useState(null);
  const [assets, setAssets] = useState([]);
  const [machines, setMachines] = useState([]);
  const [err, setErr] = useState(null);
  const [log, setLog] = useState({
    asset_id: "",
    production_unit: "bricks",
    cement_in: "",
    sand_in: "",
    blocks_out: "",
    yield_out: "",
    labor_cost: "",
    machine_hours: "",
    quality_status: "pass",
    external_ref: "",
  });
  const [maint, setMaint] = useState({ equipment_id: "", issue_description: "", cost: "" });

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [s, ast, m] = await Promise.all([
        fetchProductionSummary(null, null),
        fetchProductionAssets(),
        fetchProductionMachines(),
      ]);
      setSummary(s);
      setAssets(Array.isArray(ast?.assets) ? ast.assets : []);
      setMachines(Array.isArray(m?.machines) ? m.machines : []);
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Load failed");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function submitLog(e) {
    e.preventDefault();
    setErr(null);
    try {
      await api.post("/production/log", {
        asset_id: Number(log.asset_id),
        production_unit: log.production_unit,
        cement_in: log.cement_in ? Number(log.cement_in) : null,
        sand_in: log.sand_in ? Number(log.sand_in) : null,
        blocks_out: log.blocks_out ? Number(log.blocks_out) : null,
        yield_out: log.yield_out ? Number(log.yield_out) : null,
        labor_cost: log.labor_cost ? Number(log.labor_cost) : null,
        machine_hours: log.machine_hours ? Number(log.machine_hours) : null,
        quality_status: log.quality_status || null,
        external_ref: log.external_ref.trim() || null,
      });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Log failed");
    }
  }

  async function submitMaint(e) {
    e.preventDefault();
    setErr(null);
    try {
      await createMaintenanceLog({
        equipment_id: Number(maint.equipment_id),
        issue_description: maint.issue_description.trim(),
        cost: maint.cost ? Number(maint.cost) : 0,
      });
      setMaint({ equipment_id: "", issue_description: "", cost: "" });
    } catch (e) {
      setErr(e?.response?.data?.detail || e?.message || "Maintenance failed");
    }
  }

  const totals = summary;

  return (
    <div>
      <h1 className="biz-page-title">Production</h1>
      {err && <p className="cc-error">{err}</p>}

      {totals && totals.ok !== false && (
        <div className="cc-card">
          <h2>Period summary</h2>
          <div className="biz-grid-2" style={{ fontSize: 14 }}>
            <div>
              Logs: <strong>{totals.log_count ?? "—"}</strong>
            </div>
            <div>
              Bricks / blocks out: <strong>{totals.total_blocks_out ?? "—"}</strong>
            </div>
            <div>
              Yield out: <strong>{totals.total_yield_out ?? "—"}</strong>
            </div>
            <div>
              Labour ₹: <strong>{totals.total_labor_cost_inr ?? "—"}</strong>
            </div>
          </div>
        </div>
      )}

      <div className="cc-card">
        <h2>Daily production log</h2>
        <p className="cc-muted" style={{ fontSize: 12 }}>
          Pick an asset (kiln / line). Use bricks fields for hollow bricks; yield for oil / food SKUs.
        </p>
        <form onSubmit={submitLog} style={{ display: "grid", gap: 8 }}>
          <select
            className="cc-select"
            value={log.asset_id}
            onChange={(e) => setLog((l) => ({ ...l, asset_id: e.target.value }))}
            required
          >
            <option value="">Asset / machine</option>
            {assets.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.category})
              </option>
            ))}
          </select>
          <input
            className="cc-input"
            placeholder="Unit (bricks, kg, L, …)"
            value={log.production_unit}
            onChange={(e) => setLog((l) => ({ ...l, production_unit: e.target.value }))}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Cement in"
              value={log.cement_in}
              onChange={(e) => setLog((l) => ({ ...l, cement_in: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Sand in"
              value={log.sand_in}
              onChange={(e) => setLog((l) => ({ ...l, sand_in: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Bricks out"
              value={log.blocks_out}
              onChange={(e) => setLog((l) => ({ ...l, blocks_out: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Yield out (oil / mix)"
              value={log.yield_out}
              onChange={(e) => setLog((l) => ({ ...l, yield_out: e.target.value }))}
            />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Labour ₹"
              value={log.labor_cost}
              onChange={(e) => setLog((l) => ({ ...l, labor_cost: e.target.value }))}
            />
            <input
              className="cc-input"
              type="number"
              step="any"
              placeholder="Machine hours"
              value={log.machine_hours}
              onChange={(e) => setLog((l) => ({ ...l, machine_hours: e.target.value }))}
            />
            <select
              className="cc-select"
              value={log.quality_status}
              onChange={(e) => setLog((l) => ({ ...l, quality_status: e.target.value }))}
            >
              <option value="pass">QC pass</option>
              <option value="fail">QC fail</option>
              <option value="hold">Hold</option>
            </select>
          </div>
          <input
            className="cc-input"
            placeholder="Batch / shift ref"
            value={log.external_ref}
            onChange={(e) => setLog((l) => ({ ...l, external_ref: e.target.value }))}
          />
          <button type="submit" className="cc-btn cc-btn-primary">
            Save log
          </button>
        </form>
      </div>

      <div className="cc-card">
        <h2>Machine maintenance</h2>
        <form onSubmit={submitMaint} style={{ display: "grid", gap: 8 }}>
          <select
            className="cc-select"
            value={maint.equipment_id}
            onChange={(e) => setMaint((m) => ({ ...m, equipment_id: e.target.value }))}
            required
          >
            <option value="">Equipment</option>
            {machines.map((a) => (
              <option key={`eq-${a.id}`} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <input
            className="cc-input"
            placeholder="Issue"
            value={maint.issue_description}
            onChange={(e) => setMaint((m) => ({ ...m, issue_description: e.target.value }))}
            required
          />
          <input
            className="cc-input"
            type="number"
            step="any"
            placeholder="Cost ₹"
            value={maint.cost}
            onChange={(e) => setMaint((m) => ({ ...m, cost: e.target.value }))}
          />
          <button type="submit" className="cc-btn cc-btn-secondary">
            Log maintenance
          </button>
        </form>
      </div>

      <p className="cc-muted" style={{ fontSize: 12 }}>
        Cost per unit (rough): divide period labour + maintenance in Expenses by yield from summary.
      </p>
    </div>
  );
}
