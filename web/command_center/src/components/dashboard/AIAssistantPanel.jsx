import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { postChatQuery, fetchMyOrganizations } from "../../api/commandCenterApi.js";
import { showToastDedup } from "../../lib/toastDedup.js";
import { runAIAction, getActionConfirmation } from "../../lib/aiActionHandler.js";
import { AI_MOCK_INSIGHTS } from "../../lib/aiMockInsights.js";

export default function AIAssistantPanel() {
  const navigate = useNavigate();
  const location = useLocation();
  const jarvisBootstrapRef = useRef(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [raw, setRaw] = useState("");
  const [insights, setInsights] = useState([]);
  const [busyKey, setBusyKey] = useState(null);
  const [agentMode, setAgentMode] = useState(false);
  const [pendingId, setPendingId] = useState(null);
  const [agentHint, setAgentHint] = useState("");
  const [proposals, setProposals] = useState([]);
  const [speakReplies, setSpeakReplies] = useState(false);
  const [listening, setListening] = useState(false);
  const [tamilVoice, setTamilVoice] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [jarvisOrgId, setJarvisOrgId] = useState("");
  const [orgOptions, setOrgOptions] = useState([]);

  useEffect(() => {
    const st = location.state;
    if (!st?.jarvisPrefill || jarvisBootstrapRef.current) return;
    jarvisBootstrapRef.current = true;
    setMessage(String(st.jarvisPrefill));
    if (st.jarvisAgent) setAgentMode(true);
    navigate(
      { pathname: location.pathname, search: location.search, hash: location.hash },
      { replace: true, state: {} },
    );
  }, [location, navigate]);

  useEffect(() => {
    let cancelled = false;
    fetchMyOrganizations()
      .then((data) => {
        const rows = Array.isArray(data) ? data : data?.items || data?.organizations || [];
        if (!cancelled) setOrgOptions(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

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
      const partialConfirm =
        pendingId && opts.confirmToolIndex != null && Number.isFinite(Number(opts.confirmToolIndex));
      const partialReject =
        pendingId && opts.rejectToolIndex != null && Number.isFinite(Number(opts.rejectToolIndex));
      const isPartialPending = partialConfirm || partialReject;
      const m = (opts.textOverride ?? message).trim();
      if (!isPartialPending && (!m || loading)) return;
      const confirming = opts.confirmPending === true && pendingId && !isPartialPending;
      const useAgentMode = opts.forceAgentMode != null ? !!opts.forceAgentMode : agentMode;
      setLoading(true);
      setError(null);
      if (!confirming && !isPartialPending) {
        setRaw("");
        setInsights([]);
        setProposals([]);
        setChatMessages((prev) => [...prev, { role: "user", text: m, ts: Date.now() }]);
      }
      if (isPartialPending) {
        setAgentHint(partialReject ? "Removing proposal…" : "Executing selected action…");
      } else {
        setAgentHint(confirming ? "Executing confirmed tools…" : useAgentMode ? "Jarvis is analyzing…" : "");
      }
      try {
        const data = await postChatQuery(isPartialPending ? "" : m, {
          agent_mode: !!(useAgentMode || confirming || isPartialPending),
          agent_confirm: !!confirming,
          agent_pending_id: confirming || isPartialPending ? pendingId : null,
          agent_confirm_tool_index: partialConfirm ? Number(opts.confirmToolIndex) : undefined,
          agent_reject_tool_index: partialReject ? Number(opts.rejectToolIndex) : undefined,
          jarvis_context_org_id: jarvisOrgId || undefined,
        });
        if (data?.error && !data?.narrative) {
          setError(String(data.error));
          showToastDedup({ type: "error", message: String(data.error) });
          return;
        }
        const txt = String(data?.narrative || data?.response || "").trim();
        setRaw(txt);
        if (data?.groq_model) {
          setAgentHint(`Used model: ${data.groq_model}`);
        }

        if (data?.needs_confirmation && data?.agent_pending_id) {
          setPendingId(data.agent_pending_id);
          setProposals(Array.isArray(data.proposals) ? data.proposals : []);
          setAgentHint("Review proposals — Confirm or cancel.");
          setChatMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              text: txt,
              ts: Date.now(),
              proposals: data.proposals,
              toolResults: data.tool_results,
              needsConfirmation: true,
            },
          ]);
          showToastDedup({ type: "info", message: "Review and confirm Jarvis actions" });
          return;
        }
        setPendingId(null);
        setAgentHint("");
        setProposals([]);

        if (data?.agent_mode) {
          setChatMessages((prev) => [
            ...prev,
            { role: "assistant", text: txt, ts: Date.now(), toolResults: data.tool_results },
          ]);
          showToastDedup({ type: "success", message: "Jarvis completed" });
          setInsights([]);
          const line = txt;
          if (speakReplies && line && typeof window !== "undefined" && window.speechSynthesis) {
            try {
              window.speechSynthesis.cancel();
              const u = new SpeechSynthesisUtterance(line.slice(0, 2000));
              u.lang = tamilVoice ? "ta-IN" : "en-IN";
              window.speechSynthesis.speak(u);
            } catch {
              /* ignore */
            }
          }
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
    [loading, message, safeParseInsights, agentMode, pendingId, speakReplies, tamilVoice, jarvisOrgId],
  );

  const confirmProposalAt = useCallback(
    (index) => {
      if (loading || !pendingId) return;
      send({ confirmToolIndex: index });
    },
    [loading, pendingId, send],
  );

  const rejectProposalAt = useCallback(
    (index) => {
      if (loading || !pendingId) return;
      send({ rejectToolIndex: index });
    },
    [loading, pendingId, send],
  );

  const runQuick = useCallback(
    (text, useAgent) => {
      setAgentMode(!!useAgent);
      setMessage(text);
      send({ textOverride: text, forceAgentMode: useAgent });
    },
    [send],
  );

  const doUndo = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await postChatQuery("", { agent_undo: true });
      if (data?.error && !data?.narrative) {
        setError(String(data.error));
        showToastDedup({ type: "error", message: String(data.error) });
        return;
      }
      const txt = String(data?.narrative || data?.response || "").trim();
      setRaw(txt);
      showToastDedup({ type: "success", message: "Undo processed" });
    } catch (e) {
      const d = e?.response?.data?.detail;
      const msg = typeof d === "string" ? d : e?.message || "Undo failed";
      setError(msg);
      showToastDedup({ type: "error", message: msg });
    } finally {
      setLoading(false);
    }
  }, [loading]);

  const startVoice = useCallback(() => {
    if (typeof window === "undefined") return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      showToastDedup({ type: "warning", message: "Voice input not supported in this browser" });
      return;
    }
    const rec = new SR();
    rec.lang = tamilVoice ? "ta-IN" : "en-IN";
    rec.continuous = false;
    rec.interimResults = false;
    setListening(true);
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    rec.onresult = (ev) => {
      const t = ev.results?.[0]?.[0]?.transcript;
      if (t) setMessage((prev) => `${(prev || "").trim()} ${t}`.trim());
    };
    try {
      rec.start();
    } catch {
      setListening(false);
    }
  }, [tamilVoice]);

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
            setProposals([]);
          }}
        />
        <span>Jarvis agent mode (tools + confirm)</span>
      </label>
      <div style={{ marginBottom: 12 }}>
        <span className="cc-muted" style={{ fontSize: 13, display: "block", marginBottom: 6 }}>
          Business context (Jarvis tools)
        </span>
        <select
          className="cc-textarea"
          style={{ maxWidth: 360, padding: 8, minHeight: "unset" }}
          value={jarvisOrgId}
          onChange={(e) => setJarvisOrgId(e.target.value)}
        >
          <option value="">Active workspace (JWT)</option>
          {orgOptions.map((row) => (
            <option key={row.organization?.id ?? row.id} value={row.organization?.id ?? row.id}>
              {row.organization?.name || `Organization ${row.organization?.id}`}
            </option>
          ))}
        </select>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, cursor: "pointer" }}>
        <input type="checkbox" checked={speakReplies} onChange={(e) => setSpeakReplies(e.target.checked)} />
        <span>Speak Jarvis replies (text-to-speech)</span>
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, cursor: "pointer" }}>
        <input type="checkbox" checked={tamilVoice} onChange={(e) => setTamilVoice(e.target.checked)} />
        <span>Tamil voice input / TTS (ta-IN)</span>
      </label>
      <div
        style={{
          maxHeight: 240,
          overflowY: "auto",
          marginBottom: 12,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: 8,
          borderRadius: 10,
          border: "1px solid var(--cc-border, #e5e7eb)",
          background: "#fafafa",
        }}
      >
        {chatMessages.length === 0 ? (
          <div className="cc-muted" style={{ fontSize: 13 }}>
            Chat appears here (WhatsApp-style). Enable Jarvis for tools and confirmations.
          </div>
        ) : null}
        {chatMessages.map((cm, i) => (
          <div
            key={`${cm.ts}_${i}`}
            style={{
              alignSelf: cm.role === "user" ? "flex-end" : "flex-start",
              maxWidth: "94%",
            }}
          >
            <div className="cc-muted" style={{ fontSize: 11, marginBottom: 2 }}>
              {cm.role === "user" ? "You" : "Jarvis"} · {new Date(cm.ts).toLocaleTimeString()}
            </div>
            <div
              style={{
                padding: "10px 14px",
                borderRadius: 14,
                background: cm.role === "user" ? "rgba(37, 99, 235, 0.14)" : "#fff",
                border: cm.role === "user" ? "none" : "1px solid #e5e7eb",
                whiteSpace: "pre-wrap",
                fontSize: 14,
              }}
            >
              {cm.text}
            </div>
            {Array.isArray(cm.toolResults) && cm.toolResults.length > 0 ? (
              <div className="cc-muted" style={{ fontSize: 11, marginTop: 4 }}>
                Tools: {cm.toolResults.map((t) => t.tool).join(", ")}
              </div>
            ) : null}
          </div>
        ))}
        {loading ? (
          <div className="cc-muted" style={{ fontSize: 13, fontStyle: "italic" }}>
            Jarvis is working…
          </div>
        ) : null}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        {[
          ["Today Brief", "Call get_today_brief and summarize my day in 5 bullets.", true],
          ["Check Stock", "Call get_stock_status and list low-stock alerts.", true],
          ["Add Sale", "I want to record a quick cash sale — ask me for amount and items.", true],
          ["Find Scheme", "Call find_govt_schemes for food processing in Tamil Nadu.", true],
          ["Stock Signal", "Call analyze_stock_opportunity for RELIANCE intraday.", true],
          ["Add Meeting", "Schedule a meeting tomorrow 11am IST titled Vendor review.", true],
        ].map(([label, q, am]) => (
          <button
            type="button"
            key={label}
            className="cc-btn cc-btn-secondary"
            disabled={loading}
            onClick={() => runQuick(q, am)}
          >
            {label}
          </button>
        ))}
      </div>
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
          {loading && pendingId ? "Executing tools…" : agentHint}
        </p>
      ) : null}
      {pendingId && proposals.length > 0 ? (
        <div className="cc-card" style={{ marginBottom: 12, background: "rgba(37, 99, 235, 0.06)" }}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Proposed actions</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {proposals.map((p, i) => (
              <div
                key={`${p.tool || "t"}_${p.index ?? i}`}
                style={{
                  padding: 12,
                  borderRadius: 10,
                  border: "1px solid #e5e7eb",
                  background: "#fff",
                  fontSize: 14,
                }}
              >
                <div style={{ marginBottom: 10 }}>{p.summary || p.tool || "Action"}</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="cc-btn cc-btn-primary"
                    disabled={loading}
                    onClick={() => confirmProposalAt(p.index ?? i)}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    className="cc-btn cc-btn-secondary"
                    disabled={loading}
                    onClick={() => rejectProposalAt(p.index ?? i)}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div style={{ marginTop: 16, display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" className="cc-btn cc-btn-primary" disabled={loading} onClick={() => send({})}>
          {loading ? "Running…" : "Send"}
        </button>
        <button
          type="button"
          className="cc-btn cc-btn-secondary"
          disabled={loading || listening}
          onClick={startVoice}
          title="Voice input (Web Speech API)"
        >
          {listening ? "Listening…" : "Voice"}
        </button>
        <button type="button" className="cc-btn cc-btn-secondary" disabled={loading} onClick={doUndo}>
          Undo last action
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
