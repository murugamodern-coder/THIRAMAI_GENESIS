import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import {
  postChatQuery,
  fetchMyOrganizations,
  postAgentCommand,
  ensureAgentCorrelationId,
} from "../../api/commandCenterApi.js";
import { showToastDedup } from "../../lib/toastDedup.js";
import { runAIAction, getActionConfirmation } from "../../lib/aiActionHandler.js";
import { AI_MOCK_INSIGHTS } from "../../lib/aiMockInsights.js";

function insightPriorityRank(p) {
  if (p === "high") return 0;
  if (p === "medium") return 1;
  return 2;
}

const InsightCard = memo(function InsightCard({
  insight,
  idx,
  criticalIdx,
  pillClassForPriority,
  busyKey,
  loading,
  onRunAction,
}) {
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
  const [agenticPlanMode, setAgenticPlanMode] = useState(false);
  const [executionState, setExecutionState] = useState(null);
  const [voiceAutoSend, setVoiceAutoSend] = useState(true);
  const recognitionRef = useRef(null);
  const chatScrollRef = useRef(null);
  const composerRef = useRef(null);
  const [composerBottomOffset, setComposerBottomOffset] = useState(0);
  const [composerHeight, setComposerHeight] = useState(0);
  const [isMobileViewport, setIsMobileViewport] = useState(false);

  const startExecutionTracking = useCallback((commandText) => {
    const cmd = String(commandText || "").trim();
    if (!cmd) return;
    setExecutionState({
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      command: cmd,
      status: "running",
      progress: 0,
      steps: [
        { label: "Step 1: Searching...", status: "running" },
        { label: "Step 2: Analyzing...", status: "pending" },
        { label: "Step 3: Result ready", status: "pending" },
      ],
      finishedAt: null,
    });
  }, []);

  const finishExecutionTracking = useCallback((status) => {
    setExecutionState((prev) => {
      if (!prev) return prev;
      const ok = status === "success";
      return {
        ...prev,
        status: ok ? "success" : "error",
        progress: ok ? 100 : Math.max(prev.progress, 66),
        steps: prev.steps.map((s, idx) => {
          if (idx < 2) return { ...s, status: "done" };
          return { ...s, status: ok ? "done" : "error" };
        }),
        finishedAt: Date.now(),
      };
    });
  }, []);

  const speakText = useCallback(
    (text) => {
      const line = String(text || "").trim();
      if (!speakReplies || !line || typeof window === "undefined" || !window.speechSynthesis) return;
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(line.slice(0, 2000));
        utterance.lang = tamilVoice ? "ta-IN" : "en-IN";
        window.speechSynthesis.speak(utterance);
      } catch {
        /* ignore speech errors */
      }
    },
    [speakReplies, tamilVoice],
  );

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
      if (!isPartialPending && !confirming && agenticPlanMode) {
        setLoading(true);
        setError(null);
        setRaw("");
        setInsights([]);
        setProposals([]);
        setChatMessages((prev) => [...prev, { role: "user", text: m, ts: Date.now() }]);
        startExecutionTracking(m);
        try {
          const corr = ensureAgentCorrelationId("thiramai_cc_agent_thread");
          const path = location.pathname || "";
          const os_key = path.includes("/research")
            ? "research"
            : path.includes("/stock")
              ? "stock"
              : "stock";
          const pdata = await postAgentCommand({
            command: m,
            os_key,
            execution_mode: "paper",
            correlation_id: corr,
          });
          const summary = [
            `**${pdata.title || "Agent plan"}**`,
            "",
            `Task id: \`${pdata.task_id}\``,
            pdata.correlation_id ? `Thread: \`${String(pdata.correlation_id).slice(0, 12)}…\`` : "",
            pdata.requires_approval ? "\nApprove steps in the **Research / Stock** workflow panel (live logs stream there)." : "",
          ]
            .filter(Boolean)
            .join("\n");
          setChatMessages((prev) => [
            ...prev,
            { role: "assistant", text: summary, ts: Date.now(), agentPlan: pdata },
          ]);
          finishExecutionTracking("success");
          showToastDedup({ type: "success", message: "Agent plan ready — approve steps in the workflow panel." });
        } catch (e) {
          const msg = e?.response?.data?.detail || e?.message || "Agent command failed";
          setError(msg);
          finishExecutionTracking("error");
          showToastDedup({ type: "error", message: String(msg) });
        } finally {
          setLoading(false);
        }
        return;
      }
      setLoading(true);
      setError(null);
      if (!confirming && !isPartialPending) {
        setRaw("");
        setInsights([]);
        setProposals([]);
        setChatMessages((prev) => [...prev, { role: "user", text: m, ts: Date.now() }]);
        startExecutionTracking(m);
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
          finishExecutionTracking("error");
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
          finishExecutionTracking("success");
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
          finishExecutionTracking("success");
          showToastDedup({ type: "success", message: "Jarvis completed" });
          setInsights([]);
          speakText(txt);
          return;
        }

        const parsed = safeParseInsights(data) || safeParseInsights(txt);
        if (parsed && parsed.length > 0) {
          setInsights(parsed);
          finishExecutionTracking("success");
          showToastDedup({ type: "success", message: "Insights generated" });
          speakText(txt || "Insights generated.");
        } else {
          setInsights([]);
          finishExecutionTracking("success");
          showToastDedup({
            type: "warning",
            message: "No structured insights returned",
            actionLabel: "Load example",
            onAction: () => setInsights(AI_MOCK_INSIGHTS),
          });
          speakText(txt || "No structured insights were returned.");
        }
      } catch (e) {
        const d = e?.response?.data?.detail;
        const msg = typeof d === "string" ? d : e?.message || "Request failed";
        setError(msg);
        finishExecutionTracking("error");
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
    [
      loading,
      message,
      safeParseInsights,
      agentMode,
      pendingId,
      jarvisOrgId,
      agenticPlanMode,
      location.pathname,
      startExecutionTracking,
      finishExecutionTracking,
      speakText,
    ],
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

  useEffect(() => {
    const handler = (event) => {
      const txt = String(event?.detail?.command || "").trim();
      if (!txt) return;
      setAgenticPlanMode(true);
      setAgentMode(false);
      setMessage(txt);
      send({ textOverride: txt, forceAgentMode: false });
    };
    window.addEventListener("thiramai-global-command", handler);
    return () => window.removeEventListener("thiramai-global-command", handler);
  }, [send]);

  useEffect(() => {
    if (!loading) return undefined;
    const timer = setInterval(() => {
      setExecutionState((prev) => {
        if (!prev || prev.status !== "running") return prev;
        const steps = [...prev.steps];
        const runningIdx = steps.findIndex((s) => s.status === "running");
        if (runningIdx === -1) return prev;
        if (runningIdx < steps.length - 2) {
          steps[runningIdx] = { ...steps[runningIdx], status: "done" };
          steps[runningIdx + 1] = { ...steps[runningIdx + 1], status: "running" };
          return { ...prev, steps, progress: Math.min(90, prev.progress + 33) };
        }
        return { ...prev, progress: Math.min(95, prev.progress + 5) };
      });
    }, 900);
    return () => clearInterval(timer);
  }, [loading]);

  const startVoice = useCallback(() => {
    if (typeof window === "undefined") return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      showToastDedup({ type: "warning", message: "Voice input not supported in this browser" });
      return;
    }
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        /* ignore */
      }
      recognitionRef.current = null;
    }
    const rec = new SR();
    rec.lang = tamilVoice ? "ta-IN" : "en-IN";
    rec.continuous = false;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    recognitionRef.current = rec;
    setListening(true);
    rec.onend = () => {
      recognitionRef.current = null;
      setListening(false);
    };
    rec.onerror = () => {
      recognitionRef.current = null;
      setListening(false);
      showToastDedup({ type: "warning", message: "Voice input failed. Please try again." });
    };
    rec.onresult = (ev) => {
      const t = ev.results?.[0]?.[0]?.transcript;
      const spokenText = String(t || "").trim();
      if (!spokenText) return;
      if (voiceAutoSend && !loading) {
        setMessage(spokenText);
        send({ textOverride: spokenText });
      } else {
        setMessage((prev) => `${(prev || "").trim()} ${spokenText}`.trim());
      }
    };
    try {
      rec.start();
    } catch {
      setListening(false);
      recognitionRef.current = null;
    }
  }, [tamilVoice, voiceAutoSend, loading, send]);

  const stopVoice = useCallback(() => {
    const rec = recognitionRef.current;
    if (!rec) return;
    try {
      rec.stop();
    } catch {
      /* ignore */
    }
    recognitionRef.current = null;
    setListening(false);
  }, []);

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.stop?.();
      } catch {
        /* ignore */
      }
      recognitionRef.current = null;
      if (typeof window !== "undefined" && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const updateMobile = () => setIsMobileViewport(window.innerWidth < 768);
    const updateKeyboardOffset = () => {
      const vv = window.visualViewport;
      if (!vv || window.innerWidth >= 768) {
        setComposerBottomOffset(0);
        return;
      }
      const keyboard = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop));
      setComposerBottomOffset(keyboard);
    };
    updateMobile();
    updateKeyboardOffset();
    window.addEventListener("resize", updateMobile);
    window.addEventListener("resize", updateKeyboardOffset);
    window.visualViewport?.addEventListener("resize", updateKeyboardOffset);
    window.visualViewport?.addEventListener("scroll", updateKeyboardOffset);
    return () => {
      window.removeEventListener("resize", updateMobile);
      window.removeEventListener("resize", updateKeyboardOffset);
      window.visualViewport?.removeEventListener("resize", updateKeyboardOffset);
      window.visualViewport?.removeEventListener("scroll", updateKeyboardOffset);
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const el = composerRef.current;
    if (!el) return undefined;
    const updateHeight = () => setComposerHeight(Math.ceil(el.getBoundingClientRect().height));
    updateHeight();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(updateHeight);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    });
  }, [chatMessages, loading, pendingId, executionState?.status, executionState?.progress]);

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

  const sortedInsights = Array.isArray(insights) ? insights.slice() : [];
  sortedInsights.sort((a, b) => insightPriorityRank(a?.priority) - insightPriorityRank(b?.priority));
  const criticalIdx = sortedInsights.findIndex((x) => x?.priority === "high");
  const orgRows = Array.isArray(orgOptions) ? orgOptions : [];

  return (
    <div className="cc-card pb-40 md:pb-0 lg:sticky lg:top-6">
      <h2>Decision engine</h2>
      <p className="cc-muted" style={{ marginTop: -8, marginBottom: 16 }}>
        Ask for insights, or enable <strong>Jarvis</strong> to create tasks, log expenses, schedule meetings, and more
        (with a confirmation step).
      </p>
      <label style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={agenticPlanMode}
          onChange={(e) => {
            setAgenticPlanMode(e.target.checked);
            if (e.target.checked) setAgentMode(false);
          }}
        />
        <span>Agentic workflow (plan → approve — FastAPI /api/agent/command)</span>
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, cursor: "pointer" }}>
        <input
          type="checkbox"
          checked={agentMode}
          onChange={(e) => {
            setAgentMode(e.target.checked);
            if (e.target.checked) setAgenticPlanMode(false);
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
          {orgRows.map((row) => (
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
      <label style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, cursor: "pointer" }}>
        <input type="checkbox" checked={voiceAutoSend} onChange={(e) => setVoiceAutoSend(e.target.checked)} />
        <span>Auto-send command after voice capture</span>
      </label>
      <div
        ref={chatScrollRef}
        className="mb-3 flex max-h-[55vh] flex-col gap-2 overflow-y-auto rounded-xl border border-slate-700/60 bg-slate-100/95 p-2 md:max-h-72"
        style={{
          WebkitOverflowScrolling: "touch",
          overscrollBehavior: "contain",
          scrollBehavior: "smooth",
          paddingBottom: isMobileViewport ? composerHeight + 12 : 8,
        }}
      >
        {executionState ? (
          <div
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 12,
              padding: "10px 12px",
              background: "#fff",
              marginBottom: 8,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#334155" }}>Execution tracking</div>
              <div className="cc-muted" style={{ fontSize: 11 }}>
                {executionState.status === "running"
                  ? "Running"
                  : executionState.status === "success"
                    ? "Completed"
                    : "Failed"}
              </div>
            </div>
            <div
              className="cc-muted"
              style={{
                fontSize: 12,
                marginBottom: 8,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {executionState.command}
            </div>
            <div style={{ height: 6, background: "#e2e8f0", borderRadius: 999, marginBottom: 8 }}>
              <div
                style={{
                  height: "100%",
                  width: `${Math.max(0, Math.min(100, executionState.progress || 0))}%`,
                  borderRadius: 999,
                  transition: "width 250ms ease",
                  background: executionState.status === "error" ? "#ef4444" : "#2563eb",
                }}
              />
            </div>
            <div style={{ display: "grid", gap: 4 }}>
              {executionState.steps.map((s, idx) => (
                <div key={`${executionState.id}_${idx}`} style={{ fontSize: 12, color: "#334155" }}>
                  <span style={{ marginRight: 6 }}>
                    {s.status === "done"
                      ? "[done]"
                      : s.status === "running"
                        ? "[...]"
                        : s.status === "error"
                          ? "[x]"
                          : "[ ]"}
                  </span>
                  {s.label}
                </div>
              ))}
            </div>
          </div>
        ) : null}
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
      <div className="mb-3 hidden flex-wrap gap-2 sm:flex">
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
            className="cc-btn cc-btn-secondary min-h-11 px-4"
            disabled={loading}
            onClick={() => runQuick(q, am)}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        ref={composerRef}
        className="fixed inset-x-0 bottom-0 z-40 border-t border-slate-800 bg-slate-950/95 p-3 backdrop-blur md:static md:z-auto md:border-0 md:bg-transparent md:p-0"
        style={{
          bottom: isMobileViewport ? `max(env(safe-area-inset-bottom), ${composerBottomOffset}px)` : undefined,
        }}
      >
        <textarea
          className="cc-textarea mb-2 min-h-24 md:min-h-28"
          placeholder='Try: "Review inventory risks and pending approvals. Return JSON insights."'
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send();
          }}
          onFocus={() => {
            const el = chatScrollRef.current;
            if (!el) return;
            requestAnimationFrame(() => {
              el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
            });
          }}
        />
        {agentHint ? (
          <p className="cc-muted mb-2 text-xs md:text-sm">
            {loading && pendingId ? "Executing tools…" : agentHint}
          </p>
        ) : null}
        <div className="mt-1 flex flex-wrap items-center gap-2 md:mt-3 md:gap-3">
          <button type="button" className="cc-btn cc-btn-primary min-h-11 px-5" disabled={loading} onClick={() => send({})}>
            {loading ? "Running…" : "Send"}
          </button>
          <button
            type="button"
            className="cc-btn cc-btn-secondary min-h-11 px-4"
            disabled={loading}
            onClick={listening ? stopVoice : startVoice}
            title="Voice input (Web Speech API)"
          >
            {listening ? "Stop listening" : "Voice"}
          </button>
          <button type="button" className="cc-btn cc-btn-secondary min-h-11 px-4" disabled={loading} onClick={doUndo}>
            Undo
          </button>
          {pendingId ? (
            <button
              type="button"
              className="cc-btn cc-btn-primary min-h-11 px-4"
              disabled={loading}
              onClick={() => send({ confirmPending: true })}
            >
              {loading ? "Working…" : "Confirm"}
            </button>
          ) : null}
          <button
            type="button"
            className="cc-btn cc-btn-secondary hidden min-h-11 px-4 sm:inline-flex"
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
          <span className="cc-muted hidden text-xs md:inline">Ctrl+Enter to send</span>
        </div>
      </div>
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
                    className="cc-btn cc-btn-primary min-h-11 px-4"
                    disabled={loading}
                    onClick={() => confirmProposalAt(p.index ?? i)}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    className="cc-btn cc-btn-secondary min-h-11 px-4"
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
