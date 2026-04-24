import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchIntegrationLogs, fetchIntegrations, postIntegration, postIntegrationTest } from "../api/commandCenterApi.js";
import { showToastDedup } from "../lib/toastDedup.js";

const CHANNELS = ["email", "whatsapp", "sms"];

function pretty(v) {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export default function IntegrationsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyType, setBusyType] = useState("");
  const [logs, setLogs] = useState([]);
  const [forms, setForms] = useState(() => ({
    email: { enabled: false, configText: "{}" },
    whatsapp: { enabled: false, configText: "{}" },
    sms: { enabled: false, configText: "{}" },
  }));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [out, logsOut] = await Promise.all([fetchIntegrations(), fetchIntegrationLogs(80)]);
      const items = Array.isArray(out?.items) ? out.items : [];
      const logItems = Array.isArray(logsOut?.items) ? logsOut.items : [];
      setRows(items);
      setLogs(logItems);
      setForms((prev) => {
        const next = { ...prev };
        for (const t of CHANNELS) {
          const row = items.find((x) => String(x?.type || "") === t);
          next[t] = {
            enabled: !!row?.enabled,
            configText: pretty(row?.config_json || {}),
          };
        }
        return next;
      });
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : "Unable to load integrations" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const configHints = useMemo(
    () => ({
      email:
        '{\n  "smtp_host":"smtp.gmail.com",\n  "smtp_port":587,\n  "smtp_username":"you@gmail.com",\n  "smtp_password":"app_password",\n  "from_email":"you@gmail.com",\n  "smtp_tls":true,\n  "default_to":"ops@company.com"\n}',
      whatsapp:
        '{\n  "provider":"twilio",\n  "account_sid":"AC...",\n  "auth_token":"...",\n  "from_number":"+14155238886",\n  "default_to":"+919000000000"\n}',
      sms:
        '{\n  "api_url":"https://provider.example/send",\n  "api_token":"...",\n  "from_number":"THIRAMAI",\n  "default_to":"+919000000000"\n}',
    }),
    [],
  );

  async function save(type) {
    const form = forms[type];
    let config_json = {};
    try {
      config_json = JSON.parse(form.configText || "{}");
    } catch {
      showToastDedup({ type: "warning", message: `${type}: config_json must be valid JSON` });
      return;
    }
    setBusyType(type);
    try {
      await postIntegration({ type, config_json, enabled: !!form.enabled });
      showToastDedup({ type: "success", message: `${type} integration saved` });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : `Save failed for ${type}` });
    } finally {
      setBusyType("");
    }
  }

  async function runTest(type) {
    const form = forms[type];
    let cfg = {};
    try {
      cfg = JSON.parse(form.configText || "{}");
    } catch {
      cfg = {};
    }
    let payload = {};
    if (type === "email") {
      payload = { to: cfg.default_to || "", subject: "Thiramai Test", body: "Email integration test message." };
    } else {
      payload = { number: cfg.default_to || "", message: `${type} integration test from Thiramai.` };
    }
    setBusyType(`${type}_test`);
    try {
      const out = await postIntegrationTest({ type, payload });
      if (out?.ok) showToastDedup({ type: "success", message: `${type} test sent` });
      else showToastDedup({ type: "warning", message: out?.result?.error || `${type} test failed` });
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      showToastDedup({ type: "error", message: typeof d === "string" ? d : `Test failed for ${type}` });
    } finally {
      setBusyType("");
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h1 className="text-xl font-semibold text-slate-100">Integrations</h1>
        <p className="mt-1 text-sm text-slate-400">Connect email, WhatsApp, and SMS channels for real-world actions.</p>
      </div>
      {loading ? <div className="text-sm text-slate-400">Loading integrations...</div> : null}
      <div className="grid gap-4 lg:grid-cols-3">
        {CHANNELS.map((type) => (
          <div key={type} className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase text-slate-100">{type}</h2>
              <label className="inline-flex items-center gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={!!forms[type]?.enabled}
                  onChange={(e) => setForms((p) => ({ ...p, [type]: { ...p[type], enabled: e.target.checked } }))}
                />
                enabled
              </label>
            </div>
            <textarea
              className="h-52 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-xs text-slate-100"
              value={forms[type]?.configText || ""}
              onChange={(e) => setForms((p) => ({ ...p, [type]: { ...p[type], configText: e.target.value } }))}
              placeholder={configHints[type]}
            />
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-60"
                disabled={busyType === type}
                onClick={() => save(type)}
              >
                {busyType === type ? "Saving..." : "Save"}
              </button>
              <button
                type="button"
                className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 disabled:opacity-60"
                disabled={busyType === `${type}_test`}
                onClick={() => runTest(type)}
              >
                {busyType === `${type}_test` ? "Testing..." : "Test"}
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Configured channels</h2>
        <div className="space-y-2">
          {rows.map((r) => (
            <div key={r.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-200">
              {r.type} - {r.enabled ? "enabled" : "disabled"}
            </div>
          ))}
          {!rows.length ? <div className="text-sm text-slate-400">No channels configured yet.</div> : null}
        </div>
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="mb-3 text-sm font-semibold text-slate-100">Outgoing activity</h2>
        <div className="space-y-2">
          {logs.map((l) => (
            <div key={l.id} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3 text-sm">
              <div className="text-slate-100">
                {l.channel} -{">"} {l.recipient}{" "}
                <span className={l.status === "success" ? "text-emerald-300" : "text-red-300"}>{l.status}</span>
              </div>
              <div className="mt-1 text-xs text-slate-400">
                {l.created_at || ""}
                {l.error_message ? ` | ${l.error_message}` : ""}
              </div>
            </div>
          ))}
          {!logs.length ? <div className="text-sm text-slate-400">No outgoing messages yet.</div> : null}
        </div>
      </div>
    </div>
  );
}
