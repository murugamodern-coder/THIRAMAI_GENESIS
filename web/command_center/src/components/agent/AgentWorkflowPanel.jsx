import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ensureAgentCorrelationId,
  fetchAgentMissions,
  getAgentPlan,
  postAgentApprove,
  postAgentCommand,
  streamAgentPlan,
} from "../../api/commandCenterApi.js";

/** Production THIRAMAI agentic workflow — Plan → Approve → Execute + live logs (SSE + poll fallback). */
function AgentWorkflowPanelInner({
  osKey = "research",
  title = "Jarvis · Agentic workflow",
  correlationStorageKey = "thiramai_agent_correlation_id",
  showMissionPicker = true,
}) {
  const [command, setCommand] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [plan, setPlan] = useState(null);
  const [approveSlider, setApproveSlider] = useState(0);
  const [executionMode, setExecutionMode] = useState(() => {
    try {
      const v = (window.localStorage.getItem("thiramai_execution_mode") || "paper").toLowerCase();
      return v === "live" ? "live" : "paper";
    } catch {
      return "paper";
    }
  });
  const [missions, setMissions] = useState([]);
  const logsEndRef = useRef(null);
  const streamAbortRef = useRef(null);

  const threadId = useMemo(() => ensureAgentCorrelationId(correlationStorageKey), [correlationStorageKey]);

  const refreshPlan = useCallback(async (taskId) => getAgentPlan(taskId), []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [plan?.execution_logs]);

  useEffect(() => {
    if (!plan?.task_id) return undefined;
    streamAbortRef.current?.abort();
    const ac = new AbortController();
    streamAbortRef.current = ac;

    streamAgentPlan(
      plan.task_id,
      (payload) => {
        if (payload?.task_id) setPlan(payload);
      },
      ac.signal,
    ).catch(() => {
      /* fallback: interval below */
    });

    const tick = async () => {
      try {
        const next = await refreshPlan(plan.task_id);
        if (next?.task_id) setPlan(next);
      } catch {
        /* offline */
      }
    };
    const id = setInterval(tick, 900);
    return () => {
      clearInterval(id);
      ac.abort();
    };
  }, [plan?.task_id, refreshPlan]);

  useEffect(() => {
    if (!showMissionPicker) return undefined;
    let cancelled = false;
    fetchAgentMissions({ limit: 25, os_key: osKey })
      .then((data) => {
        if (!cancelled) setMissions(Array.isArray(data?.items) ? data.items : []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [osKey, showMissionPicker, plan?.task_id]);

  const submitCommand = async () => {
    const q = command.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const data = await postAgentCommand({
        command: q,
        os_key: osKey,
        execution_mode: executionMode,
        correlation_id: threadId,
      });
      setPlan(data);
      setApproveSlider(0);
      setCommand("");
    } catch (e) {
      setError(e?.message || String(e));
      setPlan(null);
    } finally {
      setLoading(false);
    }
  };

  const approveStep = async (signal) => {
    if (!plan?.task_id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await postAgentApprove(plan.task_id, {
        signal,
        execution_mode: executionMode === "live" ? "live" : "paper",
      });
      if (data.task_id) setPlan(data);
      else if (plan.task_id) setPlan(await refreshPlan(plan.task_id));
      setApproveSlider(0);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const requiresApproval = plan?.requires_approval;
  const logs = Array.isArray(plan?.execution_logs) ? plan.execution_logs : [];

  const onSwipeRelease = () => {
    if (approveSlider >= 92) approveStep("success");
    setApproveSlider(0);
  };

  const loadMission = async (taskId) => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getAgentPlan(taskId);
      if (data?.task_id) setPlan(data);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  const modeBtn = (mode, label, sub, activeBorder, activeBg) => (
    <button
      type="button"
      onClick={() => {
        setExecutionMode(mode);
        try {
          window.localStorage.setItem("thiramai_execution_mode", mode);
        } catch {
          /* ignore */
        }
      }}
      style={{
        flex: "1 1 140px",
        padding: "12px 14px",
        borderRadius: 12,
        border: executionMode === mode ? `3px solid ${activeBorder}` : "2px solid var(--cc-border, #e5e7eb)",
        background: executionMode === mode ? activeBg : "var(--cc-surface, #fff)",
        color: "var(--cc-text, #111)",
        fontWeight: 700,
        fontSize: 13,
        cursor: "pointer",
      }}
    >
      {label}
      <div style={{ fontSize: 10, fontWeight: 400, marginTop: 4, opacity: 0.85 }}>{sub}</div>
    </button>
  );

  return (
    <div
      className="cc-card"
      style={{
        marginBottom: 20,
        padding: 16,
      }}
    >
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 10, color: "var(--cc-text, #111)" }}>{title}</div>
      <div style={{ fontSize: 12, color: "var(--cc-muted, #666)", marginBottom: 12 }}>
        Connected to <code>/api/agent/command</code>
        {" · "}
        thread <code style={{ fontSize: 11 }}>{String(threadId).slice(0, 8)}…</code>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        {modeBtn("paper", "PAPER", "Simulation / internal — default", "#378ADD", "#378ADD18")}
        {modeBtn("live", "LIVE", "Broker path — capital at risk", "#E24B4A", "#E24B4A18")}
      </div>

      {showMissionPicker && missions.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="cc-muted" style={{ fontSize: 12, marginBottom: 6 }}>
            Recent missions ({osKey})
          </div>
          <select
            className="cc-textarea"
            style={{ minHeight: 40, width: "100%", maxWidth: 420 }}
            value=""
            onChange={(e) => loadMission(e.target.value)}
          >
            <option value="">Resume a saved mission…</option>
            {missions.map((m) => (
              <option key={m.task_id} value={m.task_id}>
                {(m.title || "Untitled").slice(0, 48)} · {m.task_id?.slice(0, 8)}…
              </option>
            ))}
          </select>
        </div>
      )}

      <textarea
        className="cc-textarea"
        rows={3}
        value={command}
        onChange={(e) => setCommand(e.target.value)}
        placeholder={`Ask Jarvis (${osKey} OS) — plans run through Tavily + Groq after you approve search steps.`}
        disabled={loading}
      />
      <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="cc-btn cc-btn-primary" disabled={loading || !command.trim()} onClick={submitCommand}>
          {loading ? "Planning…" : "Generate plan"}
        </button>
        {error && (
          <span style={{ fontSize: 12, color: "#b91c1c" }}>
            {error}
          </span>
        )}
      </div>

      {plan?.steps && (
        <div style={{ marginTop: 16 }}>
          <div className="cc-muted" style={{ fontSize: 12, marginBottom: 8 }}>
            {plan.title}{" "}
            · task <code style={{ fontSize: 11 }}>{plan.task_id}</code>
            {plan.correlation_id && (
              <>
                {" "}
                · corr <code style={{ fontSize: 11 }}>{String(plan.correlation_id).slice(0, 12)}…</code>
              </>
            )}
          </div>
          <ol style={{ paddingLeft: 18, margin: "0 0 12px 0" }}>
            {plan.steps.map((s) => (
              <li key={s.step} style={{ fontSize: 13, marginBottom: 6 }}>
                <strong>{s.action}</strong> — {s.description}{" "}
                <span
                  style={{
                    marginLeft: 8,
                    fontSize: 10,
                    padding: "2px 6px",
                    borderRadius: 6,
                    background: s.status === "pending_approval" ? "#ede9fe" : "#f3f4f6",
                  }}
                >
                  {s.status}
                </span>
              </li>
            ))}
          </ol>

          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Thinking & execution logs</div>
            <div
              style={{
                fontFamily: "ui-monospace, monospace",
                fontSize: 11,
                lineHeight: 1.45,
                maxHeight: 220,
                overflowY: "auto",
                padding: 10,
                borderRadius: 8,
                background: "#0f172a",
                border: "1px solid #1e293b",
                color: "#cbd5e1",
              }}
            >
              {logs.length === 0 ? (
                <span style={{ color: "#64748b" }}>Awaiting steps…</span>
              ) : (
                logs.map((line, i) => (
                  <div key={`${line.ts}-${i}`}>
                    <span style={{ color: "#475569" }}>{line.ts ? `${line.ts} ` : ""}</span>
                    {line.message}
                  </div>
                ))
              )}
              <div ref={logsEndRef} />
            </div>
          </div>

          {requiresApproval && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color: "#b45309", marginBottom: 8 }}>Next step requires approval</div>
              <button
                type="button"
                className="cc-btn cc-btn-primary"
                disabled={loading}
                style={{ width: "100%", maxWidth: 400 }}
                onClick={() => approveStep("success")}
              >
                Execute next step
              </button>
              <div style={{ marginTop: 12, maxWidth: 400 }}>
                <div className="cc-muted" style={{ fontSize: 11, marginBottom: 4 }}>
                  Swipe to approve
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={approveSlider}
                  onChange={(e) => setApproveSlider(Number(e.target.value))}
                  onMouseUp={onSwipeRelease}
                  onTouchEnd={onSwipeRelease}
                  style={{ width: "100%" }}
                />
              </div>
              <button type="button" className="cc-btn cc-btn-secondary" disabled={loading} onClick={() => approveStep("reject")} style={{ marginTop: 10 }}>
                Reject remaining steps
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(AgentWorkflowPanelInner);
