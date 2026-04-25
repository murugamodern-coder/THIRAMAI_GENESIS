import { useCallback, useEffect, useRef, useState } from "react";

import api from "../../api/client.js";
import BrainResponseBlock from "../BrainResponseBlock.jsx";
import { postBrainCommand } from "../../lib/brainExecuteClient.js";
import { showToastDedup } from "../../lib/toastDedup.js";

const ENABLE_VOICE_INPUT = false;
const ACTIVE_PRESENCE_LINES = [
  "Analyzing signals...",
  "Evaluating execution path...",
  "Scanning for outcomes...",
  "Verifying system state...",
  "Recalculating next move...",
];
const IDLE_PRESENCE_LINES = ["Monitoring system state...", "No new signals.", "Standing by."];

function naturalResponseDelay(seq) {
  return 200 + (((seq || 1) * 73) % 301);
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function normalizeStep(raw, idx) {
  if (raw && typeof raw === "object") {
    return {
      id: String(raw.id || `s${idx + 1}`),
      label: String(raw.label || raw.title || `Step ${idx + 1}`),
      status: String(raw.status || "pending"),
      stepOrder: Number(raw.step_order || idx + 1),
      result: Object.prototype.hasOwnProperty.call(raw, "result") ? raw.result : null,
    };
  }
  return { id: `s${idx + 1}`, label: String(raw || `Step ${idx + 1}`), status: "pending", stepOrder: idx + 1, result: null };
}

export default function AIAssistantPanel() {
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [listening, setListening] = useState(false);
  const [messages, setMessages] = useState([]);
  const [approvingMissionId, setApprovingMissionId] = useState(null);
  const [presenceLine, setPresenceLine] = useState("");
  const [idleLine, setIdleLine] = useState("");
  const [interactionSeq, setInteractionSeq] = useState(0);
  const [latestResponseTs, setLatestResponseTs] = useState(null);
  const recognitionRef = useRef(null);
  const endRef = useRef(null);
  const presenceIndexRef = useRef(0);
  const idleIndexRef = useRef(0);
  const lastAssistant = messages.findLast?.((m) => m.role === "assistant");
  const hasError = Boolean(lastAssistant?.error);
  const baselineInsight = loading
    ? "Execution path under evaluation."
    : hasError
      ? "Risk detected. Awaiting correction."
      : messages.length > 1
        ? "Execution stable. Monitoring outcomes."
        : "Command channel ready";
  const systemInsight = presenceLine || idleLine || baselineInsight;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    if (loading) return undefined;
    setIdleLine("");
    const idleDelay = 5000 + ((interactionSeq % 6) * 700);
    const timer = window.setTimeout(() => {
      const line = IDLE_PRESENCE_LINES[idleIndexRef.current % IDLE_PRESENCE_LINES.length];
      idleIndexRef.current += 1;
      setIdleLine(line);
    }, idleDelay);
    return () => window.clearTimeout(timer);
  }, [interactionSeq, loading]);

  const approveMission = useCallback(
    async (missionId) => {
      if (!missionId) return;
      setApprovingMissionId(missionId);
      try {
        const { data } = await api.post(`/mission/${encodeURIComponent(missionId)}/approve`);
        const nextSteps = Array.isArray(data?.steps) ? data.steps.map(normalizeStep) : [];
        const nextStatus = String(data?.status || "running");
        setMessages((prev) =>
          prev.map((m) =>
            Number(m?.missionId) === Number(missionId)
              ? { ...m, missionStatus: nextStatus, status: nextStatus, steps: nextSteps }
              : m,
          ),
        );
        showToastDedup({ type: "success", message: "Mission approved and execution started." });
      } catch (e) {
        const d = e?.response?.data?.detail;
        const err = typeof d === "string" ? d : e?.message || "Approve mission failed";
        showToastDedup({ type: "error", message: err });
      } finally {
        setApprovingMissionId(null);
      }
    },
    [],
  );

  const submit = useCallback(
    async (textOverride = "") => {
      const text = String(textOverride || message).trim();
      if (!text || loading) return;
      const nextSeq = presenceIndexRef.current + 1;
      const line = ACTIVE_PRESENCE_LINES[presenceIndexRef.current % ACTIVE_PRESENCE_LINES.length];
      presenceIndexRef.current = nextSeq;
      setPresenceLine(line);
      setIdleLine("");
      setInteractionSeq((v) => v + 1);
      setLoading(true);
      setMessages((prev) => [...prev, { role: "user", text, ts: Date.now() }]);
      if (!textOverride) setMessage("");
      try {
        const data = await postBrainCommand(text);
        await delay(naturalResponseDelay(nextSeq));
        const ts = Date.now();
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            ts,
            brain: data,
          },
        ]);
        setLatestResponseTs(ts);
        window.setTimeout(() => setLatestResponseTs((current) => (current === ts ? null : current)), 260);
      } catch (e) {
        const d = e?.response?.data?.detail;
        const err = typeof d === "string" ? d : e?.message || "Brain execute failed";
        await delay(naturalResponseDelay(nextSeq));
        const ts = Date.now();
        setMessages((prev) => [...prev, { role: "assistant", ts, error: err }]);
        setLatestResponseTs(ts);
        window.setTimeout(() => setLatestResponseTs((current) => (current === ts ? null : current)), 260);
        showToastDedup({ type: "error", message: err });
      } finally {
        setPresenceLine("");
        setInteractionSeq((v) => v + 1);
        setLoading(false);
      }
    },
    [loading, message],
  );

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
    rec.lang = "en-IN";
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
      const spoken = String(ev.results?.[0]?.[0]?.transcript || "").trim();
      if (!spoken) return;
      setMessage(spoken);
      submit(spoken);
    };
    try {
      rec.start();
    } catch {
      setListening(false);
      recognitionRef.current = null;
    }
  }, [submit]);

  useEffect(() => {
    const missionRows = messages.filter(
      (m) =>
        m?.role === "assistant" &&
        Number(m?.missionId) > 0 &&
        !["completed"].includes(String(m?.missionStatus || "").toLowerCase()),
    );
    if (!missionRows.length) return undefined;
    let timerId = null;
    const poll = async () => {
      try {
        const updates = await Promise.all(
          missionRows.map(async (m) => {
            const { data } = await api.get(`/mission/${encodeURIComponent(m.missionId)}`);
            return { missionId: Number(m.missionId), data };
          }),
        );
        setMessages((prev) =>
          prev.map((msg) => {
            const hit = updates.find((u) => Number(u.missionId) === Number(msg?.missionId));
            if (!hit) return msg;
            const nextSteps = Array.isArray(hit.data?.steps) ? hit.data.steps.map(normalizeStep) : msg.steps;
            const nextStatus = String(hit.data?.status || msg.missionStatus || msg.status || "");
            return { ...msg, missionStatus: nextStatus, status: nextStatus, steps: nextSteps };
          }),
        );
      } catch {
        // Silent polling failures to keep chat usable.
      } finally {
        timerId = window.setTimeout(poll, 2000);
      }
    };
    timerId = window.setTimeout(poll, 1000);
    return () => {
      if (timerId) window.clearTimeout(timerId);
    };
  }, [messages]);

  return (
    <div className="mx-auto w-full max-w-[720px]">
      <p
        className="mb-7 text-center text-[15px] leading-7 text-white transition-opacity duration-300"
        style={{ color: "#ffffff", fontWeight: 500 }}
        aria-live="polite"
      >
        {systemInsight}
      </p>
      <section className="flex flex-col gap-4">
        <div className="max-h-[62vh] min-h-72 overflow-y-auto rounded-[2rem] bg-slate-950/80 p-5 shadow-[0_28px_90px_-56px_rgba(15,23,42,0.95)]">
          {messages.length === 0 ? (
            <div className="min-h-56" aria-hidden="true" />
          ) : null}

          <div className="space-y-4">
            {messages.map((m, idx) => {
              if (m.role === "user") {
                return (
                  <div key={`u_${m.ts}_${idx}`} className="flex justify-end">
                    <div className="max-w-[85%] rounded-3xl bg-sky-500/20 px-5 py-3 text-[15px] font-medium leading-7 text-white">
                      {m.text}
                    </div>
                  </div>
                );
              }
              return (
                <div key={`a_${m.ts}_${idx}`} className={`flex justify-start ${m.ts === latestResponseTs ? "cc-response-enter" : ""}`}>
                  <div className="w-full max-w-[92%]">
                    {m.error ? (
                      <div className="rounded-3xl bg-red-950/80 px-5 py-4 text-[15px] font-medium leading-7 text-red-100">
                        {m.error}
                      </div>
                    ) : m.brain ? (
                      <BrainResponseBlock brain={m.brain} />
                    ) : (
                      <div className="rounded-3xl bg-slate-900/80 px-5 py-4 text-[15px] font-medium leading-7 text-[#e2e8f0]">
                        {m.type === "mission" ? (
                          <div className="rounded-2xl bg-purple-500/10 p-3">
                            <div className="mb-2 text-xs uppercase tracking-wide text-purple-300">Mission</div>
                            <div className="text-xs text-purple-200">
                              mission_id: {m.missionId || "n/a"} | status: {m.missionStatus || m.status || "planned"}
                            </div>
                            {String(m.missionStatus || "").toLowerCase() !== "completed" ? (
                              <button
                                type="button"
                                className="mt-3 rounded-md bg-purple-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-purple-500 disabled:opacity-80"
                                disabled={approvingMissionId === m.missionId}
                                onClick={() => approveMission(m.missionId)}
                              >
                                {approvingMissionId === m.missionId ? "Approving..." : "Approve"}
                              </button>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-white">No response data.</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {loading ? (
              <div className="rounded-3xl bg-slate-900/80 px-5 py-3 text-sm font-medium leading-7 text-slate-200">
                thinking<span className="cc-thinking-dots">...</span>
              </div>
            ) : null}
            <div ref={endRef} />
          </div>
        </div>

        <div className="rounded-[1.75rem] bg-slate-950/80 p-2.5 shadow-[0_18px_70px_-42px_rgba(56,189,248,0.38)] ring-1 ring-slate-800/80">
          <div className="flex gap-2.5">
            <input
              className="flex-1 rounded-2xl border border-transparent bg-slate-950 px-5 py-4 text-[15px] font-medium leading-6 text-white outline-none shadow-inner shadow-black/20 transition duration-300 placeholder:text-slate-200 focus:border-sky-400/80 focus:shadow-[0_0_0_4px_rgba(56,189,248,0.18)]"
              placeholder="Type a command…"
              value={message}
              onChange={(e) => {
                setMessage(e.target.value);
                setIdleLine("");
                setInteractionSeq((v) => v + 1);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
            />
            <button
              type="button"
              onClick={() => submit()}
              disabled={loading}
              className="rounded-2xl bg-slate-100 px-5 py-4 text-sm font-medium text-slate-950 shadow-[0_10px_30px_-18px_rgba(255,255,255,0.65)] transition duration-300 hover:-translate-y-0.5 hover:bg-white active:scale-[0.97] disabled:translate-y-0 disabled:opacity-80"
            >
              Send
            </button>
            {ENABLE_VOICE_INPUT ? (
              <button
                type="button"
                onClick={startVoice}
                disabled={loading || listening}
                className="rounded-2xl border border-slate-800 px-4 py-3 text-sm text-[#e2e8f0] hover:bg-slate-900 disabled:opacity-80"
                title="Voice input"
              >
                {listening ? "Listening…" : "Voice"}
              </button>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
