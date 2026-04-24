import { useCallback, useEffect, useState } from "react";

import { fetchLearningInsights, fetchLearningStrategies } from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

export default function LearningInsightsPage() {
  const [insights, setInsights] = useState(null);
  const [strategies, setStrategies] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    try {
      const [ins, strat] = await Promise.all([
        fetchLearningInsights({ limit: 200, ...(refresh ? { refresh: true } : {}) }),
        fetchLearningStrategies({ ...(refresh ? { refresh: true } : {}) }),
      ]);
      setInsights(ins || null);
      setStrategies(Array.isArray(strat?.items) ? strat.items : []);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load learning insights" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Learning / Insights</h1>
        <p className="mt-1 text-sm text-slate-400">Self-learning engine feedback from outcomes, wins/losses, and strategy optimization.</p>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-100">Performance summary</h2>
          <button
            type="button"
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200"
            onClick={() => load(true)}
          >
            Refresh optimization
          </button>
        </div>
        {loading ? <div className="text-sm text-slate-400">Loading...</div> : null}
        {insights ? (
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              win rate: {(Number(insights.win_rate || 0) * 100).toFixed(1)}%
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              profit trend MA(5): {Number(insights?.profit_trend?.ma_short || 0).toFixed(2)}
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              profit trend MA(20): {Number(insights?.profit_trend?.ma_long || 0).toFixed(2)}
            </div>
          </div>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Best strategies</h2>
          <div className="space-y-2">
            {(insights?.best_strategies || []).map((s, idx) => (
              <div key={`b_${idx}`} className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-100">
                {s.source_type} | win rate: {(Number(s.win_rate || 0) * 100).toFixed(1)}% | avg pnl: {Number(s.avg_pnl || 0).toFixed(2)}
              </div>
            ))}
            {!(insights?.best_strategies || []).length ? <div className="text-sm text-slate-400">No strategy insights yet.</div> : null}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Worst patterns</h2>
          <div className="space-y-2">
            {(insights?.worst_patterns || []).map((s, idx) => (
              <div key={`w_${idx}`} className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-100">
                {s.source_type} | win rate: {(Number(s.win_rate || 0) * 100).toFixed(1)}% | avg pnl: {Number(s.avg_pnl || 0).toFixed(2)}
              </div>
            ))}
            {!(insights?.worst_patterns || []).length ? <div className="text-sm text-slate-400">No risk patterns yet.</div> : null}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Recommendations</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-200">
          {(insights?.recommendations || []).map((r, idx) => (
            <li key={`r_${idx}`}>{r}</li>
          ))}
        </ul>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Strategy profiles</h2>
        <div className="space-y-2">
          {strategies.map((s) => (
            <div key={s.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              {s.domain} | performance: {Number(s.performance_score || 0).toFixed(2)}
            </div>
          ))}
          {!strategies.length ? <div className="text-sm text-slate-400">No strategy profiles yet.</div> : null}
        </div>
      </div>
    </div>
  );
}
