import { useCallback, useEffect, useRef, useState } from "react";

import api from "../../api/client.js";
import BrainResponseBlock from "../BrainResponseBlock.jsx";
import { postBrainCommand } from "../../lib/brainExecuteClient.js";
import { showToastDedup } from "../../lib/toastDedup.js";

const ENABLE_VOICE_INPUT = false;

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
  const recognitionRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

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
      setLoading(true);
      setMessages((prev) => [...prev, { role: "user", text, ts: Date.now() }]);
      if (!textOverride) setMessage("");
      try {
        const data = await postBrainCommand(text);
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            ts: Date.now(),
            brain: data,
          },
        ]);
      } catch (e) {
        const d = e?.response?.data?.detail;
        const err = typeof d === "string" ? d : e?.message || "Brain execute failed";
        setMessages((prev) => [...prev, { role: "assistant", ts: Date.now(), error: err }]);
        showToastDedup({ type: "error", message: err });
      } finally {
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
    <div className="mx-auto w-full max-w-3xl">
      <section className="flex flex-col gap-3">
        <div className="max-h-[62vh] min-h-64 overflow-y-auto rounded-3xl border border-slate-900 bg-slate-950/50 p-4 shadow-[0_24px_80px_-48px_rgba(15,23,42,0.9)]">
          {messages.length === 0 ? (
            <div className="flex min-h-52 items-center justify-center text-center text-sm text-slate-500">
              Ask for a decision, action, or system check.
            </div>
          ) : null}

          <div className="space-y-3">
            {messages.map((m, idx) => {
              if (m.role === "user") {
                return (
                  <div key={`u_${m.ts}_${idx}`} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl bg-blue-600/20 px-4 py-2 text-sm text-slate-100">{m.text}</div>
                  </div>
                );
              }
              return (
                <div key={`a_${m.ts}_${idx}`} className="flex justify-start">
                  <div className="w-full max-w-[92%]">
                    {m.error ? (
                      <div className="rounded-2xl border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-200">
                        {m.error}
                      </div>
                    ) : m.brain ? (
                      <BrainResponseBlock brain={m.brain} />
                    ) : (
                      <div className="rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-100">
                        {m.type === "mission" ? (
                          <div className="rounded-lg border border-purple-500/30 bg-purple-500/10 p-3">
                            <div className="mb-2 text-xs uppercase tracking-wide text-purple-300">Mission</div>
                            <div className="text-xs text-purple-200">
                              mission_id: {m.missionId || "n/a"} | status: {m.missionStatus || m.status || "planned"}
                            </div>
                            {String(m.missionStatus || "").toLowerCase() !== "completed" ? (
                              <button
                                type="button"
                                className="mt-3 rounded-md bg-purple-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-purple-500 disabled:opacity-60"
                                disabled={approvingMissionId === m.missionId}
                                onClick={() => approveMission(m.missionId)}
                              >
                                {approvingMissionId === m.missionId ? "Approving..." : "Approve"}
                              </button>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-slate-400">No response data.</span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {loading ? (
              <div className="rounded-2xl bg-slate-900/50 px-4 py-3 text-xs text-slate-500">Thinking…</div>
            ) : null}
            <div ref={endRef} />
          </div>
        </div>

        <div className="rounded-3xl border border-slate-900 bg-slate-950/60 p-3">
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-slate-600"
              placeholder="Type a command…"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
            />
            <button
              type="button"
              onClick={() => submit()}
              disabled={loading}
              className="rounded-2xl bg-white px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-slate-200 disabled:opacity-50"
            >
              Send
            </button>
            {ENABLE_VOICE_INPUT ? (
              <button
                type="button"
                onClick={startVoice}
                disabled={loading || listening}
                className="rounded-2xl border border-slate-800 px-4 py-3 text-sm text-slate-300 hover:bg-slate-900 disabled:opacity-60"
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
