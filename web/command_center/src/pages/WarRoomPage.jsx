import { useCallback, useEffect, useState } from "react";

import {
  fetchAutonomyHeartbeat,
  fetchAutonomyState,
  fetchDecisionTrace,
  fetchFeedbackAccuracy,
  fetchFeedbackDrift,
  fetchGoalsProgress,
  fetchMemoryRecall,
  fetchPredictRiskAlerts,
  fetchPredictSummary,
  fetchSystemOverview,
  fetchSystemRuntimeHealth,
  postSystemBootstrap,
  postSystemEmergencyStop,
  postGovernanceKillSwitch,
  startMoneyLoop,
  stopMoneyLoop,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

function Dot({ color = "bg-slate-500" }) {
  return <span className={`inline-flex h-2.5 w-2.5 rounded-full ${color}`} />;
}

export default function WarRoomPage() {
  const [overview, setOverview] = useState(null);
  const [trace, setTrace] = useState(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [riskLevel, setRiskLevel] = useState("medium");
  const [predict, setPredict] = useState(null);
  const [riskAlerts, setRiskAlerts] = useState([]);
  const [feedbackAccuracy, setFeedbackAccuracy] = useState(null);
  const [feedbackDrift, setFeedbackDrift] = useState(null);
  const [autonomyState, setAutonomyState] = useState(null);
  const [autonomyHeartbeat, setAutonomyHeartbeat] = useState(null);
  const [goalProgress, setGoalProgress] = useState(null);
  const [memoryRecall, setMemoryRecall] = useState(null);
  const [runtimeHealth, setRuntimeHealth] = useState(null);

  const load = useCallback(async () => {
    try {
      const out = await fetchSystemOverview();
      const pred = await fetchPredictSummary();
      const alerts = await fetchPredictRiskAlerts();
      const acc = await fetchFeedbackAccuracy();
      const drift = await fetchFeedbackDrift();
      const autonomy = await fetchAutonomyState();
      const heartbeat = await fetchAutonomyHeartbeat();
      const goals = await fetchGoalsProgress({ horizon: "week" });
      const memory = await fetchMemoryRecall({ q: "autonomy strategy decisions" });
      const health = await fetchSystemRuntimeHealth();
      setOverview(out || null);
      setPredict(pred || null);
      setRiskAlerts(Array.isArray(alerts?.alerts) ? alerts.alerts : []);
      setFeedbackAccuracy(acc || null);
      setFeedbackDrift(drift || null);
      setAutonomyState(autonomy || null);
      setAutonomyHeartbeat(heartbeat || null);
      setGoalProgress(goals || null);
      setMemoryRecall(memory || null);
      setRuntimeHealth(health || null);
      setRiskLevel(String(out?.money_loop_status?.risk_level || "medium"));
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load system overview" });
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function openTrace(executionId) {
    if (!executionId) return;
    setTraceLoading(true);
    try {
      const out = await fetchDecisionTrace(executionId);
      setTrace(out || null);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Unable to load trace" });
    } finally {
      setTraceLoading(false);
    }
  }

  async function pauseSystem() {
    try {
      await postGovernanceKillSwitch({ enabled: true, reason: "War-room pause" });
      await stopMoneyLoop();
      await load();
      showToastDedup({ type: "warning", message: "System paused" });
    } catch {
      showToastDedup({ type: "error", message: "Unable to pause system" });
    }
  }

  async function startSystem() {
    try {
      await postSystemBootstrap();
      await load();
      showToastDedup({ type: "success", message: "System bootstrap completed" });
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Unable to bootstrap system" });
    }
  }

  async function emergencyStop() {
    try {
      await postSystemEmergencyStop();
      await load();
      showToastDedup({ type: "warning", message: "Emergency stop activated" });
    } catch {
      showToastDedup({ type: "error", message: "Unable to activate emergency stop" });
    }
  }

  async function resumeSystem() {
    try {
      await postGovernanceKillSwitch({ enabled: false, reason: "War-room resume" });
      await startMoneyLoop({ max_daily_capital: Number(overview?.money_loop_status?.max_daily_capital || 50000), max_parallel_missions: Number(overview?.money_loop_status?.max_parallel_missions || 2), risk_level: riskLevel, auto_execute: !!overview?.money_loop_status?.auto_execute, run_now: false });
      await load();
      showToastDedup({ type: "success", message: "System resumed" });
    } catch {
      showToastDedup({ type: "error", message: "Unable to resume system" });
    }
  }

  async function adjustRisk() {
    try {
      await startMoneyLoop({
        max_daily_capital: Number(overview?.money_loop_status?.max_daily_capital || 50000),
        max_parallel_missions: Number(overview?.money_loop_status?.max_parallel_missions || 2),
        risk_level: riskLevel,
        auto_execute: !!overview?.money_loop_status?.auto_execute,
        run_now: false,
      });
      await load();
      showToastDedup({ type: "success", message: "Risk level updated live" });
    } catch {
      showToastDedup({ type: "error", message: "Unable to adjust risk" });
    }
  }

  const status = String(overview?.system_status || "PAUSED").toUpperCase();
  const decisions = Array.isArray(overview?.recent_decisions) ? overview.recent_decisions : [];
  const missions = Array.isArray(overview?.active_missions) ? overview.active_missions : [];

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Command Center</h1>
        <p className="mt-1 text-sm text-slate-400">War-room overview with explainable decisions.</p>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-100">
          total profit today: {Number(overview?.today_profit_loss || 0).toFixed(2)}
        </div>
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-100">
          risk exposure: {Number(overview?.risk_exposure || 0).toFixed(2)}
        </div>
        <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-4 text-sm text-slate-200">
          <div className="flex items-center gap-2">
            <Dot color={status === "RUNNING" ? "bg-emerald-400" : "bg-red-400"} />
            system status: {status}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-100">Active missions</h2>
            <div className="space-y-2">
              {missions.map((m) => (
                <div key={m.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
                  {m.title} | {m.status}
                </div>
              ))}
              {!missions.length ? <div className="text-sm text-slate-400">No active missions.</div> : null}
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-100">Money loop activity</h2>
            <div className="text-sm text-slate-200">
              active automations: {Number(overview?.active_automations || 0)} | loop risk:{" "}
              {String(overview?.money_loop_status?.risk_level || "medium")}
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-100">Prediction Panel</h2>
            <div className="text-sm text-slate-200">
              tomorrow risk: {String(predict?.predicted_risk?.risk_level || "medium")} | expected trend:{" "}
              {String(predict?.profit_trend?.trend || "neutral")}
            </div>
            <div className="mt-2 space-y-1">
              {riskAlerts.map((a, idx) => (
                <div key={`alert_${idx}`} className="text-xs text-slate-300">
                  {a.message}
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <h2 className="mb-2 text-sm font-semibold text-slate-100">Prediction Accuracy</h2>
              <div className="text-sm text-slate-200">
                accuracy: {Number(feedbackAccuracy?.accuracy_pct || 0).toFixed(2)}%
              </div>
              <div className="mt-1 text-xs text-slate-400">
                trend: {String(feedbackAccuracy?.trend || feedbackDrift?.trend || "stable")}
              </div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <h2 className="mb-2 text-sm font-semibold text-slate-100">System Trust Score</h2>
              <div className="text-sm text-slate-200">
                trust: {Number(feedbackAccuracy?.system_trust_score || 0).toFixed(2)}
              </div>
              <div className="mt-1 text-xs text-slate-400">
                calibration: {Number(feedbackAccuracy?.confidence_calibration || 0).toFixed(3)}
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-100">Autonomy Status</h2>
            <div className="text-sm text-slate-200">
              mode: {String(autonomyState?.mode || "recommend")} | pending approvals:{" "}
              {Number(autonomyHeartbeat?.pending_approvals || 0)}
            </div>
            <div className="mt-1 text-xs text-slate-400">
              drift: {String(autonomyHeartbeat?.drift?.trend || "stable")} | high-impact approvals:{" "}
              {autonomyState?.approval_required_for_high_impact ? "required" : "policy-driven"}
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-100">System Status Panel</h2>
            <div className="text-sm text-slate-200">
              state: {String(runtimeHealth?.live_state || "STOPPED")} | orgs running:{" "}
              {Number(runtimeHealth?.active_org_count || 0)}
            </div>
            <div className="mt-1 text-xs text-slate-400">
              total revenue today: {Number(runtimeHealth?.revenue_today || 0).toFixed(2)} | health:{" "}
              {String(runtimeHealth?.last_execution_status || "unknown")}
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-100">Goal + Memory Pulse</h2>
            <div className="text-sm text-slate-200">
              active goals: {Number(goalProgress?.summary?.active_goals || 0)} | avg progress:{" "}
              {Number(goalProgress?.summary?.avg_progress_pct || 0).toFixed(2)}%
            </div>
            <div className="mt-1 text-xs text-slate-400">
              recalled memory signals: {Number((memoryRecall?.items || []).length || 0)}
            </div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-100">Controls</h2>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="rounded-md border border-red-600 px-3 py-1.5 text-xs text-red-200" onClick={pauseSystem}>
                Pause system
              </button>
              <button type="button" className="rounded-md border border-emerald-600 px-3 py-1.5 text-xs text-emerald-200" onClick={startSystem}>
                Start System
              </button>
              <button type="button" className="rounded-md border border-emerald-600 px-3 py-1.5 text-xs text-emerald-200" onClick={resumeSystem}>
                Resume
              </button>
              <button type="button" className="rounded-md border border-rose-600 px-3 py-1.5 text-xs text-rose-200" onClick={emergencyStop}>
                Emergency Stop
              </button>
              <select
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200"
                value={riskLevel}
                onChange={(e) => setRiskLevel(e.target.value)}
              >
                <option value="low">low risk</option>
                <option value="medium">medium risk</option>
                <option value="high">high risk</option>
              </select>
              <button type="button" className="rounded-md border border-blue-600 px-3 py-1.5 text-xs text-blue-200" onClick={adjustRisk}>
                Adjust risk live
              </button>
            </div>
          </div>
        </div>

        <aside className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-100">Recent decisions</h2>
          <div className="space-y-2">
            {decisions.map((d) => (
              <button
                type="button"
                key={`${d.execution_id}_${d.id}`}
                onClick={() => openTrace(d.execution_id)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-left text-xs text-slate-200 hover:bg-slate-800/60"
              >
                <div className="font-medium">{d.action_type}</div>
                <div className="mt-1 text-slate-400">{d.reasoning_summary || "No reasoning captured."}</div>
              </button>
            ))}
            {!decisions.length ? <div className="text-sm text-slate-400">No recent decisions.</div> : null}
          </div>
        </aside>
      </div>

      {trace || traceLoading ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-xl border border-slate-700 bg-slate-950 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-100">Decision trace</h3>
              <button type="button" className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200" onClick={() => setTrace(null)}>
                Close
              </button>
            </div>
            {traceLoading ? <div className="text-sm text-slate-400">Loading trace...</div> : null}
            {trace ? (
              <div className="space-y-2">
                <div className="text-xs text-slate-300">intent: {trace.intent || "n/a"}</div>
                <div className="text-xs text-slate-300">reasoning: {trace.reasoning || "n/a"}</div>
                {(trace.steps || []).map((s, idx) => (
                  <div key={`tr_${idx}`} className="rounded-lg border border-slate-700 bg-slate-900/60 p-3 text-xs text-slate-200">
                    <div className="font-medium">
                      {s.label} | {s.status}
                    </div>
                    <div className="mt-1 text-slate-400">{s.reasoning || "No reasoning details."}</div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
