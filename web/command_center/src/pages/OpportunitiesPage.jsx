import { useCallback, useEffect, useState } from "react";

import { approveOpportunity, executeOpportunity, fetchOpportunities } from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

export default function OpportunitiesPage() {
  const [rows, setRows] = useState([]);
  const [best, setBest] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async (rescan = false) => {
    setLoading(true);
    try {
      const out = await fetchOpportunities({ limit: 100, ...(rescan ? { rescan: true } : {}) });
      setRows(Array.isArray(out?.items) ? out.items : []);
      setBest(out?.best_today || null);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load opportunities" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  async function onApprove(id) {
    setBusyId(id);
    try {
      await approveOpportunity(id);
      showToastDedup({ type: "success", message: "Opportunity approved" });
      await load(false);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Approve failed" });
    } finally {
      setBusyId(null);
    }
  }

  async function onExecute(id) {
    setBusyId(id);
    try {
      const out = await executeOpportunity(id);
      showToastDedup({ type: "success", message: `Executed. Estimated realized profit: ${Number(out?.realized_profit || 0).toFixed(2)}` });
      await load(false);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Execute failed" });
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Opportunities</h1>
        <p className="mt-1 text-sm text-slate-400">Intelligent money-making opportunities from trading, business, and arbitrage scans.</p>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-100">Best opportunity today</h2>
          <button
            type="button"
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200"
            onClick={() => load(true)}
          >
            Rescan
          </button>
        </div>
        {best ? (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm">
            <div className="font-medium text-emerald-200">{best.title}</div>
            <div className="mt-1 text-slate-200">
              profit: {Number(best.expected_profit || 0).toFixed(2)} | risk: {best.risk_level} | confidence:{" "}
              {Number(best.confidence || 0).toFixed(2)} | score: {Number(best.score || 0).toFixed(2)}
            </div>
          </div>
        ) : (
          <div className="text-sm text-slate-400">No opportunities yet. Click Rescan.</div>
        )}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">All opportunities</h2>
        {loading ? <div className="text-sm text-slate-400">Loading...</div> : null}
        <div className="space-y-2">
          {rows.map((r) => (
            <div key={r.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-100">{r.title}</div>
                  <div className="mt-1 text-xs text-slate-400">
                    {r.type} | status: {r.status} | profit: {Number(r.expected_profit || 0).toFixed(2)} | risk: {r.risk_level} |
                    confidence: {Number(r.confidence || 0).toFixed(2)}
                  </div>
                  <div className="mt-1 text-xs text-slate-300">{r.description}</div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="rounded-md border border-blue-600 px-2 py-1 text-xs text-blue-200 disabled:opacity-60"
                    disabled={busyId === r.id || r.status === "executed" || r.status === "approved"}
                    onClick={() => onApprove(r.id)}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="rounded-md border border-emerald-600 px-2 py-1 text-xs text-emerald-200 disabled:opacity-60"
                    disabled={busyId === r.id || r.status === "executed"}
                    onClick={() => onExecute(r.id)}
                  >
                    Execute
                  </button>
                </div>
              </div>
            </div>
          ))}
          {!rows.length && !loading ? <div className="text-sm text-slate-400">No opportunities found.</div> : null}
        </div>
      </div>
    </div>
  );
}
