import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteAutomationRule,
  fetchAutomationLogs,
  fetchAutomationRules,
  postAutomationEvaluate,
  upsertAutomationRule,
} from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

const TRIGGERS = ["inventory_updated", "new_data", "scheduled_check", "low_stock", "new_lead", "price_drop"];
const ACTIONS = ["create_mission", "notify_user", "send_email", "send_whatsapp", "reorder", "execute_trade", "opportunity"];

function emptyRule() {
  return {
    id: null,
    name: "",
    trigger_type: "inventory_updated",
    action_type: "create_mission",
    enabled: true,
    min_value: "",
    max_value: "",
    field: "quantity",
    equals: "",
    contains: "",
    mission_prompt: "",
    action_target: "",
    action_subject: "",
    action_message: "",
    require_approval: true,
  };
}

export default function AutomationPage() {
  const [rules, setRules] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ruleForm, setRuleForm] = useState(() => emptyRule());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [rulesRes, logsRes] = await Promise.all([fetchAutomationRules(), fetchAutomationLogs(80)]);
      setRules(Array.isArray(rulesRes?.items) ? rulesRes.items : []);
      setLogs(Array.isArray(logsRes?.items) ? logsRes.items : []);
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Failed to load automation data" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const mappedPayload = useMemo(() => {
    const condition_json = {
      field: String(ruleForm.field || "").trim(),
      ...(ruleForm.min_value !== "" ? { min_value: Number(ruleForm.min_value) } : {}),
      ...(ruleForm.max_value !== "" ? { max_value: Number(ruleForm.max_value) } : {}),
      ...(ruleForm.equals !== "" ? { equals: ruleForm.equals } : {}),
      ...(ruleForm.contains !== "" ? { contains: ruleForm.contains } : {}),
    };
    const action_config_json = {
      require_approval: !!ruleForm.require_approval,
      ...(ruleForm.mission_prompt ? { mission_prompt: ruleForm.mission_prompt } : {}),
      ...(ruleForm.action_target
        ? ruleForm.action_type === "send_email"
          ? { to: ruleForm.action_target }
          : { number: ruleForm.action_target }
        : {}),
      ...(ruleForm.action_subject ? { subject: ruleForm.action_subject } : {}),
      ...(ruleForm.action_message
        ? ruleForm.action_type === "send_email"
          ? { body: ruleForm.action_message }
          : { message: ruleForm.action_message }
        : {}),
    };
    return {
      id: ruleForm.id || null,
      name: ruleForm.name.trim(),
      trigger_type: ruleForm.trigger_type,
      condition_json,
      action_type: ruleForm.action_type,
      action_config_json,
      enabled: !!ruleForm.enabled,
    };
  }, [ruleForm]);

  async function submitRule(e) {
    e.preventDefault();
    if (!mappedPayload.name) {
      showToastDedup({ type: "warning", message: "Rule name is required" });
      return;
    }
    setSaving(true);
    try {
      await upsertAutomationRule(mappedPayload);
      showToastDedup({ type: "success", message: "Automation rule saved" });
      setRuleForm(emptyRule());
      await load();
    } catch (e2) {
      const d = e2?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  async function removeRule(id) {
    try {
      await deleteAutomationRule(id);
      showToastDedup({ type: "success", message: "Rule deleted" });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Delete failed" });
    }
  }

  async function runScheduledCheck() {
    try {
      const out = await postAutomationEvaluate("scheduled_check", { source: "manual_test", now: Date.now() });
      showToastDedup({ type: "success", message: `Rule evaluation finished (${Number(out?.count || 0)} match)` });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Evaluation failed" });
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Automation</h1>
        <p className="mt-1 text-sm text-slate-400">Rule-based auto decisions and actions with optional approval.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <form onSubmit={submitRule} className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="text-sm font-semibold text-slate-100">Rule builder</h2>
          <input
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="Rule name"
            value={ruleForm.name}
            onChange={(e) => setRuleForm((p) => ({ ...p, name: e.target.value }))}
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <select
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              value={ruleForm.trigger_type}
              onChange={(e) => setRuleForm((p) => ({ ...p, trigger_type: e.target.value }))}
            >
              {TRIGGERS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <select
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              value={ruleForm.action_type}
              onChange={(e) => setRuleForm((p) => ({ ...p, action_type: e.target.value }))}
            >
              {ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              placeholder="Condition field (e.g. quantity)"
              value={ruleForm.field}
              onChange={(e) => setRuleForm((p) => ({ ...p, field: e.target.value }))}
            />
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              placeholder="contains"
              value={ruleForm.contains}
              onChange={(e) => setRuleForm((p) => ({ ...p, contains: e.target.value }))}
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              placeholder="min value"
              type="number"
              value={ruleForm.min_value}
              onChange={(e) => setRuleForm((p) => ({ ...p, min_value: e.target.value }))}
            />
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              placeholder="max value"
              type="number"
              value={ruleForm.max_value}
              onChange={(e) => setRuleForm((p) => ({ ...p, max_value: e.target.value }))}
            />
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              placeholder="equals"
              value={ruleForm.equals}
              onChange={(e) => setRuleForm((p) => ({ ...p, equals: e.target.value }))}
            />
          </div>
          <input
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="Mission prompt (optional)"
            value={ruleForm.mission_prompt}
            onChange={(e) => setRuleForm((p) => ({ ...p, mission_prompt: e.target.value }))}
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              placeholder={ruleForm.action_type === "send_email" ? "Email recipient" : "Phone number"}
              value={ruleForm.action_target}
              onChange={(e) => setRuleForm((p) => ({ ...p, action_target: e.target.value }))}
            />
            <input
              className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
              placeholder="Action subject (optional)"
              value={ruleForm.action_subject}
              onChange={(e) => setRuleForm((p) => ({ ...p, action_subject: e.target.value }))}
            />
          </div>
          <input
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="Action message/body (optional)"
            value={ruleForm.action_message}
            onChange={(e) => setRuleForm((p) => ({ ...p, action_message: e.target.value }))}
          />
          <div className="flex flex-wrap gap-4 text-sm text-slate-200">
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={ruleForm.require_approval}
                onChange={(e) => setRuleForm((p) => ({ ...p, require_approval: e.target.checked }))}
              />
              approval required
            </label>
            <label className="inline-flex items-center gap-2">
              <input
                type="checkbox"
                checked={ruleForm.enabled}
                onChange={(e) => setRuleForm((p) => ({ ...p, enabled: e.target.checked }))}
              />
              enabled
            </label>
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-60"
            >
              {saving ? "Saving..." : ruleForm.id ? "Update rule" : "Create rule"}
            </button>
            <button
              type="button"
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200"
              onClick={() => setRuleForm(emptyRule())}
            >
              Reset
            </button>
            <button
              type="button"
              className="rounded-lg border border-purple-600 px-4 py-2 text-sm text-purple-200"
              onClick={runScheduledCheck}
            >
              Run scheduled check
            </button>
          </div>
        </form>

        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-100">Rules</h2>
          {loading ? <div className="text-sm text-slate-400">Loading...</div> : null}
          <div className="space-y-2">
            {rules.map((r) => (
              <div key={r.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="text-sm font-medium text-slate-100">{r.name}</div>
                    <div className="text-xs text-slate-400">
                      {r.trigger_type} -{">"} {r.action_type} ({r.enabled ? "enabled" : "disabled"})
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200"
                      onClick={() =>
                        setRuleForm({
                          id: r.id,
                          name: r.name || "",
                          trigger_type: r.trigger_type || "inventory_updated",
                          action_type: r.action_type || "create_mission",
                          enabled: !!r.enabled,
                          min_value: r?.condition_json?.min_value ?? "",
                          max_value: r?.condition_json?.max_value ?? "",
                          field: r?.condition_json?.field ?? "quantity",
                          equals: r?.condition_json?.equals ?? "",
                          contains: r?.condition_json?.contains ?? "",
                          mission_prompt: r?.action_config_json?.mission_prompt ?? "",
                          action_target:
                            r?.action_type === "send_email"
                              ? r?.action_config_json?.to ?? ""
                              : r?.action_config_json?.number ?? "",
                          action_subject: r?.action_config_json?.subject ?? "",
                          action_message:
                            r?.action_type === "send_email"
                              ? r?.action_config_json?.body ?? ""
                              : r?.action_config_json?.message ?? "",
                          require_approval: !!r?.action_config_json?.require_approval,
                        })
                      }
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="rounded-md border border-red-600 px-2 py-1 text-xs text-red-200"
                      onClick={() => removeRule(r.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
            {!rules.length && !loading ? <div className="text-sm text-slate-400">No automation rules yet.</div> : null}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Activity log</h2>
        <div className="space-y-2">
          {logs.map((l) => (
            <div key={l.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
              <div className="text-sm text-slate-100">
                {l.trigger_type} -{">"} <span className="text-blue-300">{l.action_taken}</span>
              </div>
              <div className="mt-1 text-xs text-slate-400">
                rule_id: {l.rule_id || "n/a"} | mission_id: {l?.action_result_json?.mission_id || "n/a"} | {l.created_at || ""}
              </div>
            </div>
          ))}
          {!logs.length ? <div className="text-sm text-slate-400">No automation activity yet.</div> : null}
        </div>
      </div>
    </div>
  );
}
