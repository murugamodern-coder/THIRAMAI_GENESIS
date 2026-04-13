import { memo, useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { postChatQuery } from "../../api/commandCenterApi.js";
import { showToastDedup } from "../../lib/toastDedup.js";
import { runAIAction, getActionConfirmation } from "../../lib/aiActionHandler.js";
import { AI_MOCK_INSIGHTS } from "../../lib/aiMockInsights.js";

export default function AIAssistantPanel() {
  const navigate = useNavigate();
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [raw, setRaw] = useState("");
  const [insights, setInsights] = useState([]);
  const [busyKey, setBusyKey] = useState(null);
  const [agentMode, setAgentMode] = useState(false);
  const [pendingId, setPendingId] = useState(null);
  const [agentHint, setAgentHint] = useState("");

  const priorityRank = useCallback((p) => {
    if (p === "high") return 0;
    if (p === "medium") return 1;
    return 2;
  }, []);

  const sortedInsights = useMemo(() => {
    const arr = Array.isArray(insights) ? insights.slice() : [];
    arr.sort((a, b) => priorityRank(a?.priority) - priorityRank(b?.priority));
    return arr;
  }, [insights, priorityRank]);

  const criticalIdx = useMemo(() => sortedInsights.findIndex((x) => x?.priority === "high"), [sortedInsights]);

  const safeParseInsights = useCallback((value) => {
    if (!value) return null;
    if (Array.isArray(value)) return value;
    if (Array.isArray(value?.insights)) return value.insights;
    if (Array.isArray(value?.output)) return value.output;
    if (Array.isArray(value?.results)) return value.results;

    const text =
      typeof value === "string"
        ? value
        : String(value?.narrative || value?.response || value?.text || "").trim();

    if (!text) return null;
    const start = text.indexOf("[");
    const end = text.lastIndexOf("]");
    if (start === -1 || end === -1 || end <= start) return null;
    const slice = text.slice(start, end + 1);
    try {
      const parsed = JSON.parse(slice);
      return Array.isArray(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }, []);

  const pillClassForPriority = useCallback((priority) => {
    if (priority === "high") return "cc-pill cc-pill--danger";
    if (priority === "medium") return "cc-pill cc-pill--warning";
    return "cc-pill cc-pill--neutral";
  }, []);

  const send = useCallback(
    async (opts = {}) => {
      const m = message.trim();
      if (!m || loading) return;
      const confirming = opts.confirmPending === true && pendingId;
      setLoading(true);
      setError(null);
      if (!confirming) {
        setRaw("");
        setInsights([]);
      }
      setAgentHint(confirming ? "Running confirmed actions…" : agentMode ? "THIRAMAI is thinking…" : "");
      try {
        const data = await postChatQuery(m, {
          agent_mode: !!(agentMode || confirming),
          agent_confirm: !!confirming,
          agent_pending_id: confirming ? pendingId : null,
        });
        if (data?.error && !data?.narrative) {
          setError(String(data.error));
          showToastDedup({ type: "error", message: String(data.error) });
          return;
        }
        const txt = String(data?.narrative || data?.response || "").trim();
        setRaw(txt);

        if (data?.needs_confirmation && data?.agent_pending_id) {
          setPendingId(data.agent_pending_id);
          setAgentHint("Confirm the actions below, then press Confirm.");
          showToastDedup({ type: "info", message: "Review and confirm Jarvis actions" });
          return;
        }
        setPendingId(null);
        setAgentHint("");

        if (data?.agent_mode) {
          showToastDedup({ type: "success", message: "Jarvis completed" });
          setInsights([]);
          return;
        }

        const parsed = safeParseInsights(data) || safeParseInsights(txt);
        if (parsed && parsed.length > 0) {
          setInsights(parsed);
          showToastDedup({ type: "success", message: "Insights generated" });
        } else {
          setInsights([]);
          showToastDedup({
            type: "warning",
            message: "No structured insights returned",
            actionLabel: "Load example",
            onAction: () => setInsights(AI_MOCK_INSIGHTS),
          });
        }
      } catch (e) {
        const d = e?.response?.data?.detail;
        const msg = typeof d === "string" ? d : e?.message || "Request failed";
        setError(msg);
        showToastDedup({
          type: "error",
          message: "AI request failed",
          actionLabel: "Retry",
          onAction: () => send(opts),
        });
      } finally {
        setLoading(false);
      }
    },
    [loading, message, safeParseInsights, agentMode, pendingId],
  );

  const onRunAction = useCallback(async (action, insightId) => {
      const key = `${insightId || "insight"}__${action?.type || "action"}__${JSON.stringify(action?.payload || {})}`;
      if (busyKey === key) return;

      const confirmText = getActionConfirmation(action);
      if (confirmText) {
        const ok = window.confirm(confirmText);
        if (!ok) return;
      }

      setBusyKey(key);
      showToastDedup({ type: "info", message: "Executing AI action…" });
      try {
        const out = await runAIAction(action);
        if (action?.type === "navigate" && action?.payload?.to) {
          navigate(action.payload.to);
        }
        showToastDedup({ type: "success", message: "Action completed" });
        return out;
      } catch (err) {
        const msg = err?.message || "AI action failed";
        showToastDedup({
          type: "error",
          message: msg,
          actionLabel: "Retry",
          onAction: () => {
            // Fire-and-forget retry; toast action must not throw.
            onRunAction(action, insightId);
          },
        });
        return null;
      } finally {
        setBusyKey(null);
      }
    }, [busyKey, navigate]);

  const InsightCard = useMemo(() => {
    return memo(function InsightCardInner({ insight, idx, criticalIdx, pillClassForPriority, busyKey, loading, onRunAction }) {
      const actions = Array.isArray(insight?.actions) ? insight.actions : [];
      const confidence =
        typeof insight?.confidence === "number" && Number.isFinite(insight.confidence)
          ? Math.max(0, Math.min(1, insight.confidence))
          : null;
      const isCritical = idx === criticalIdx && insight?.priority === "high";

      return (
        <div
          className="cc-card"
          style={{
            marginBottom: 16,
            borderColor: isCritical ? "rgba(187, 0, 0, 0.35)" : undefined,
            boxShadow: isCritical ? "0 8px 20px rgba(187, 0, 0, 0.10)" : undefined,
          }}
        >
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start", justifyContent: "space-between" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em" }}>
                {insight?.title || "Insight"}
              </div>
              <div className="cc-muted" style={{ marginTop: 8, fontSize: 14 }}>
                {insight?.description || "—"}
              </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-end" }}>
              <span className={pillClassForPriority(insight?.priority)}>{insight?.priority || "low"}</span>
              <div className="cc-muted" style={{ fontSize: 12 }}>
                Confidence: {confidence == null ? "—" : `${Math.round(confidence * 100)}%`}
              </div>
            </div>
          </div>

          {actions.length > 0 ? (
            <div style={{ marginTop: 16, display: "flex", gap: 16, flexWrap: "wrap" }}>
              {actions.map((a, i) => {
                const k = `${insight?.id || "insight"}__${a?.type || "action"}__${JSON.stringify(a?.payload || {})}`;
                const isBusy = busyKey === k;
                return (
                  <button
                    key={`${insight?.id || "insight"}_${i}`}
                    type="button"
                    className={i === 0 ? "cc-btn cc-btn-primary" : "cc-btn cc-btn-secondary"}
                    disabled={loading || isBusy}
                    onClick={() => onRunAction(a, insight?.id)}
                  >
                    {isBusy ? "Working…" : a?.label || "Run action"}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="cc-muted" style={{ marginTop: 16, fontSize: 12 }}>
              No actions suggested.
            </div>
          )}
        </div>
      );
    });
  }, []);

  return (
    <div className="cc-card" style={{ position: "sticky", top: 24 }}>
      <h2>Decision engine</h2>
      <p className="cc-muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Ask for insights, or enable <strong>Jarvis</strong> to create tasks, log expenses, schedule meetings, and more
        (with a confirmation step).
      </p>
      <label style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={agentMode}
          onChange={(e) => {
            setAgentMode(e.target.checked);
            setPendingId(null);
          }}
        />
        <span>Jarvis agent mode (tools + confirm)</span>
      </label>
      <textarea
        className="cc-textarea"
        placeholder='Try: "Review inventory risks and pending approvals. Return JSON insights."'
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send();
        }}
      />
      {agentHint ? (
        <p className="cc-muted" style={{ marginBottom: 8, fontSize: 13 }}>
          {agentHint}
        </p>
      ) : null}
      <div style={{ marginTop: 16, display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={() => send({})}>
          {loading ? "Running…" : "Send"}
        </button>
        {pendingId ? (
          <button
            type="button"
            className="cc-btn cc-btn-primary"
            disabled={loading}
            onClick={() => send({ confirmPending: true })}
          >
            {loading ? "Working…" : "Confirm actions"}
          </button>
        ) : null}
        <button
          type="button"
          className="cc-btn cc-btn-secondary"
          disabled={loading}
          onClick={() => {
            setError(null);
            setRaw("");
            setInsights(AI_MOCK_INSIGHTS);
            showToastDedup({ type: "info", message: "Loaded example insights" });
          }}
        >
          Load example
        </button>
        <span className="cc-muted">Ctrl+Enter to send</span>
      </div>
      {error && <p className="cc-error">{error}</p>}

      <div style={{ marginTop: 16 }}>
        {sortedInsights.length === 0 ? (
          <div
            style={{
              border: "1px dashed var(--cc-border)",
              borderRadius: 10,
              padding: 16,
              background: "#fafafa",
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600 }}>No critical insights</div>
            <div className="cc-muted" style={{ marginTop: 8 }}>
              When risk signals or pending approvals are detected, insights and recommended actions will appear here.
            </div>
          </div>
        ) : (
          sortedInsights.map((insight, idx) => (
            <InsightCard
              key={insight?.id || String(idx)}
              insight={insight}
              idx={idx}
              criticalIdx={criticalIdx}
              pillClassForPriority={pillClassForPriority}
              busyKey={busyKey}
              loading={loading}
              onRunAction={onRunAction}
            />
          ))
        )}
      </div>

      {raw ? (
        <details style={{ marginTop: 16 }}>
          <summary className="cc-muted" style={{ cursor: "pointer" }}>
            Raw AI response
          </summary>
          <pre
            style={{
              marginTop: 8,
              fontSize: 11,
              margin: 0,
              padding: 16,
              background: "#0b1220",
              color: "#e5e7eb",
              borderRadius: 10,
              overflow: "auto",
              maxHeight: 160,
            }}
          >
            {raw}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
