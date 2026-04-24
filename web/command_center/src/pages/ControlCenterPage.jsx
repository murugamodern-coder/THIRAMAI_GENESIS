import { useCallback, useEffect, useState } from "react";

import {
  fetchGovernanceGuardrails,
  fetchGovernanceLogs,
  postGovernanceGuardrail,
  postGovernanceKillSwitch,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

const DOMAINS = ["trading", "business", "automation", "global"];

function emptyForm() {
  return {
    rule_name: "",
    domain: "trading",
    enabled: true,
    condition_json: "{}",
    action_limit_json: '{"max_trade_amount_per_day": 100000}',
  };
}

export default function ControlCenterPage() {
  const [items, setItems] = useState([]);
  const [logs, setLogs] = useState([]);
  const [summary, setSummary] = useState({ daily_usage: 0, risk_exposure: 0 });
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState(() => emptyForm());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [g, l] = await Promise.all([fetchGovernanceGuardrails(), fetchGovernanceLogs(120)]);
      setItems(Array.isArray(g?.items) ? g.items : []);
      setLogs(Array.isArray(l?.items) ? l.items : []);
      setSummary(l?.summary || { daily_usage: 0, risk_exposure: 0 });
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load governance data" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function saveGuardrail(e) {
    e.preventDefault();
    let condition_json = {};
    let action_limit_json = {};
    try {
      condition_json = JSON.parse(form.condition_json || "{}");
      action_limit_json = JSON.parse(form.action_limit_json || "{}");
    } catch {
      showToastDedup({ type: "warning", message: "condition/action limit JSON must be valid" });
      return;
    }
    try {
      await postGovernanceGuardrail({
        rule_name: form.rule_name || "guardrail",
        domain: form.domain,
        enabled: !!form.enabled,
        condition_json,
        action_limit_json,
      });
      showToastDedup({ type: "success", message: "Guardrail saved" });
      setForm(emptyForm());
      await load();
    } catch (e2) {
      const d = e2?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Save failed" });
    }
  }

  async function killSwitch(enabled) {
    try {
      await postGovernanceKillSwitch({ enabled, reason: enabled ? "Manual emergency stop" : "Resume operations" });
      showToastDedup({ type: enabled ? "warning" : "success", message: enabled ? "Kill switch enabled" : "Kill switch disabled" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Kill switch update failed" });
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Control Center</h1>
        <p className="mt-1 text-sm text-slate-400">Governance, safety, limits, and emergency controls.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-200">
          daily usage: <span className="font-semibold">{Number(summary.daily_usage || 0)}</span>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm text-slate-200">
          risk exposure: <span className="font-semibold">{Number(summary.risk_exposure || 0).toFixed(2)}</span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="flex gap-2">
          <button type="button" className="rounded-lg border border-red-600 px-3 py-1.5 text-xs text-red-200" onClick={() => killSwitch(true)}>
            Emergency Stop
          </button>
          <button type="button" className="rounded-lg border border-emerald-600 px-3 py-1.5 text-xs text-emerald-200" onClick={() => killSwitch(false)}>
            Resume
          </button>
        </div>
      </div>

      <form onSubmit={saveGuardrail} className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="text-sm font-semibold text-slate-100">Guardrail config</h2>
        <div className="grid gap-2 sm:grid-cols-3">
          <input
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="Rule name"
            value={form.rule_name}
            onChange={(e) => setForm((p) => ({ ...p, rule_name: e.target.value }))}
          />
          <select
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={form.domain}
            onChange={(e) => setForm((p) => ({ ...p, domain: e.target.value }))}
          >
            {DOMAINS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <label className="inline-flex items-center gap-2 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={!!form.enabled}
              onChange={(e) => setForm((p) => ({ ...p, enabled: e.target.checked }))}
            />
            enabled
          </label>
        </div>
        <textarea
          className="h-24 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-slate-100"
          value={form.condition_json}
          onChange={(e) => setForm((p) => ({ ...p, condition_json: e.target.value }))}
          placeholder='{"when":"always"}'
        />
        <textarea
          className="h-24 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-slate-100"
          value={form.action_limit_json}
          onChange={(e) => setForm((p) => ({ ...p, action_limit_json: e.target.value }))}
          placeholder='{"max_trade_amount_per_day":100000}'
        />
        <button type="submit" className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500">
          Save Guardrail
        </button>
      </form>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Current guardrails</h2>
        {loading ? <div className="text-sm text-slate-400">Loading...</div> : null}
        <div className="space-y-2">
          {items.map((g) => (
            <div key={g.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              {g.rule_name} | {g.domain} | {g.enabled ? "enabled" : "disabled"}
            </div>
          ))}
          {!items.length && !loading ? <div className="text-sm text-slate-400">No guardrails configured.</div> : null}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Execution audit logs</h2>
        <div className="space-y-2">
          {logs.map((l) => (
            <div key={l.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              {l.action_type} | {l.source} | {l.status}
            </div>
          ))}
          {!logs.length ? <div className="text-sm text-slate-400">No execution logs yet.</div> : null}
        </div>
      </div>
    </div>
  );
}
