import { useCallback, useEffect, useState } from "react";

import {
  fetchAllocationPreview,
  fetchMoneyLoopStatus,
  fetchPredictRiskAlerts,
  fetchPredictSummary,
  startMoneyLoop,
  stopMoneyLoop,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

export default function MoneyLoopPage() {
  const [status, setStatus] = useState(null);
  const [allocationPreview, setAllocationPreview] = useState([]);
  const [predictSummary, setPredictSummary] = useState(null);
  const [predictAlerts, setPredictAlerts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    max_daily_capital: 50000,
    max_parallel_missions: 2,
    risk_level: "medium",
    auto_execute: false,
    optimizer_enabled: true,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const out = await fetchMoneyLoopStatus();
      const pred = await fetchPredictSummary();
      const alerts = await fetchPredictRiskAlerts();
      setStatus(out || null);
      setPredictSummary(pred || null);
      setPredictAlerts(Array.isArray(alerts?.alerts) ? alerts.alerts : []);
      const preview = await fetchAllocationPreview({ capital: Number(out?.config?.max_daily_capital || 50000) });
      setAllocationPreview(Array.isArray(preview?.items) ? preview.items : []);
      const cfg = out?.config || {};
      setForm((p) => ({
        ...p,
        max_daily_capital: Number(cfg.max_daily_capital || p.max_daily_capital),
        max_parallel_missions: Number(cfg.max_parallel_missions || p.max_parallel_missions),
        risk_level: String(cfg.risk_level || p.risk_level),
        auto_execute: !!cfg.auto_execute,
        optimizer_enabled: cfg.optimizer_enabled !== false,
      }));
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load money loop status" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function onStart() {
    setBusy(true);
    try {
      await startMoneyLoop({ ...form, run_now: true });
      showToastDedup({ type: "success", message: "Money loop started" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Unable to start money loop" });
    } finally {
      setBusy(false);
    }
  }

  async function onStop() {
    setBusy(true);
    try {
      await stopMoneyLoop();
      showToastDedup({ type: "warning", message: "Money loop stopped" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Unable to stop money loop" });
    } finally {
      setBusy(false);
    }
  }

  const cfg = status?.config || {};
  const actions = Array.isArray(status?.last_actions) ? status.last_actions : [];

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Money Loop</h1>
        <p className="mt-1 text-sm text-slate-400">Continuous opportunity -> mission -> execution -> learning loop.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-200">
          today profit: {Number(status?.today_profit || 0).toFixed(2)}
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-200">
          running missions: {Number(status?.running_missions || 0)}
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-200">
          status: {cfg.enabled ? "ON" : "OFF"}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Controls</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          <input
            type="number"
            min={0}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={form.max_daily_capital}
            onChange={(e) => setForm((p) => ({ ...p, max_daily_capital: Number(e.target.value || 0) }))}
            placeholder="Max daily capital"
          />
          <input
            type="number"
            min={1}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={form.max_parallel_missions}
            onChange={(e) => setForm((p) => ({ ...p, max_parallel_missions: Number(e.target.value || 1) }))}
            placeholder="Max parallel missions"
          />
          <select
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={form.risk_level}
            onChange={(e) => setForm((p) => ({ ...p, risk_level: e.target.value }))}
          >
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
          <label className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={!!form.auto_execute}
              onChange={(e) => setForm((p) => ({ ...p, auto_execute: e.target.checked }))}
            />
            auto execute
          </label>
          <label className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={!!form.optimizer_enabled}
              onChange={(e) => setForm((p) => ({ ...p, optimizer_enabled: e.target.checked }))}
            />
            optimizer enabled
          </label>
        </div>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60"
            disabled={busy}
            onClick={onStart}
          >
            Start
          </button>
          <button
            type="button"
            className="rounded-lg border border-red-600 px-4 py-2 text-sm text-red-200 disabled:opacity-60"
            disabled={busy}
            onClick={onStop}
          >
            Stop
          </button>
          <button
            type="button"
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200"
            onClick={load}
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Prediction Panel</h2>
        <div className="text-sm text-slate-200">
          tomorrow risk: {String(predictSummary?.predicted_risk?.risk_level || "medium")} | expected profit trend:{" "}
          {String(predictSummary?.profit_trend?.trend || "neutral")}
        </div>
        <div className="mt-2 space-y-1">
          {predictAlerts.map((a, idx) => (
            <div key={`pl_alert_${idx}`} className="text-xs text-slate-300">
              {a.message}
            </div>
          ))}
          {!predictAlerts.length ? <div className="text-xs text-slate-400">No predictive alerts.</div> : null}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Capital Allocation</h2>
        <div className="space-y-2">
          {allocationPreview.map((a) => (
            <div key={`alloc_${a.opportunity_id}`} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              {a.title} | allocated: {Number(a.allocated_capital || 0).toFixed(2)} | expected return:{" "}
              {Number(a.expected_return || 0).toFixed(2)}
            </div>
          ))}
          {!allocationPreview.length ? <div className="text-sm text-slate-400">No allocation preview available.</div> : null}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Last actions</h2>
        {loading ? <div className="text-sm text-slate-400">Loading...</div> : null}
        <div className="space-y-2">
          {actions.map((a) => (
            <div key={a.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              {a.action_type} | {a.status} | {a.created_at || ""}
            </div>
          ))}
          {!actions.length && !loading ? <div className="text-sm text-slate-400">No money loop actions yet.</div> : null}
        </div>
      </div>
    </div>
  );
}
