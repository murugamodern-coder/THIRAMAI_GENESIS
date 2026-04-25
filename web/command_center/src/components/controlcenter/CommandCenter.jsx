import { useEffect, useMemo, useRef, useState } from "react";

const RULE = "─────────────────────";

function isBrainExecutePayload(r) {
  if (!r || typeof r !== "object") return false;
  if (Array.isArray(r.blocks) && r.blocks.length) return false;
  return (
    Object.prototype.hasOwnProperty.call(r, "result") &&
    typeof r.result === "object" &&
    r.result !== null &&
    (Object.prototype.hasOwnProperty.call(r, "intent") ||
      Object.prototype.hasOwnProperty.call(r, "status") ||
      Object.prototype.hasOwnProperty.call(r, "plan"))
  );
}

function pickSummary(brain) {
  if (typeof brain.summary === "string" && brain.summary.trim()) return brain.summary.trim();
  const inner = brain.result && typeof brain.result === "object" ? brain.result : {};
  if (typeof inner.summary === "string" && inner.summary.trim()) return inner.summary.trim();
  const ex = brain.execution_summary;
  if (typeof ex === "string" && ex.trim()) return ex.trim();
  if (ex && typeof ex === "object") {
    const t = ex.summary ?? ex.text ?? ex.message;
    if (typeof t === "string" && t.trim()) return t.trim();
  }
  return "";
}

/** Human-readable /brain/execute style payloads (not Control Center { blocks } envelopes). */
function formatBrainExecuteResponse(brain) {
  const inner = brain.result && typeof brain.result === "object" ? brain.result : {};
  const status = String(brain.status || "").toLowerCase();
  const innerOk = inner.ok !== false && !inner.blocked;
  const topFail = brain.ok === false;
  const ok =
    !topFail &&
    brain.ok !== false &&
    innerOk &&
    !["failed", "blocked"].includes(status);
  const errRaw =
    inner.error != null
      ? String(inner.error)
      : inner.reason != null
        ? String(inner.reason)
        : "";
  const topErr = topFail ? String(brain.error || brain.detail || "").trim() : "";
  const errMsg = topErr || errRaw.trim() || (ok ? "" : "Request failed.");

  const lines = [];
  lines.push(RULE);
  lines.push(`${ok ? "✅" : "⚠️"} System Status`);
  lines.push(RULE);

  if (!ok) {
    if (inner.error === "pipeline_violation" || errMsg === "pipeline_violation") {
      const orig = inner.original_result;
      const detail =
        orig && typeof orig === "object"
          ? String(orig.error || orig.message || errMsg).trim() || errMsg
          : errMsg;
      lines.push(`⚠️ Pipeline check failed — ${detail}`);
    } else {
      lines.push(`⚠️ ${errMsg}`);
    }
  }

  const steps = Array.isArray(inner.steps) ? inner.steps : Array.isArray(brain.steps) ? brain.steps : [];
  for (const step of steps) {
    const kind = String(step.step_kind || step.kind || "step");
    const st = String(step.status || step.outcome || "").toLowerCase();
    const stepOk = step.ok !== false && !["failed", "error"].includes(st);
    const mark = stepOk ? "✅" : "❌";
    lines.push(`${kind}: ${mark}`);
  }

  const summary = pickSummary(brain);
  if (summary) {
    lines.push("");
    lines.push(`Summary: ${summary}`);
  }

  const conf = brain.confidence;
  const score = conf && typeof conf === "object" && conf.score != null ? Number(conf.score) : null;
  if (score != null && Number.isFinite(score)) {
    const pct = Math.min(100, Math.max(0, Math.round(score * 100)));
    lines.push(`Confidence: ${pct}%`);
  }

  lines.push(RULE);
  return { text: lines.join("\n"), warn: !ok };
}

function normalizeSubmitResult(raw) {
  if (!raw || typeof raw !== "object") return raw;
  if (isBrainExecutePayload(raw)) return raw;
  const msg = raw.message;
  if (typeof msg === "string" && msg.trim().startsWith("{")) {
    try {
      const j = JSON.parse(msg);
      if (isBrainExecutePayload(j)) return { ...raw, ...j, message: undefined };
    } catch {
      /* ignore */
    }
  }
  return raw;
}

export default function CommandCenter({ onSubmit, safeMode, variant = "default", actionFlashKey = 0 }) {
  const isCalm = variant === "calm";
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [enterAssistantId, setEnterAssistantId] = useState(null);
  const lastFlashKey = useRef(0);

  const [history, setHistory] = useState([
    {
      id: "seed_1",
      role: "assistant",
      text: "Channel open.",
    },
  ]);

  const [shellPulseClass, setShellPulseClass] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  useEffect(() => {
    if (!actionFlashKey || actionFlashKey === lastFlashKey.current) return;
    lastFlashKey.current = actionFlashKey;
    setShellPulseClass(true);
    const t = setTimeout(() => setShellPulseClass(false), 920);
    return () => clearTimeout(t);
  }, [actionFlashKey]);

  const placeholder = useMemo(
    () =>
      safeMode
        ? "Degraded input channel."
        : isCalm
          ? "Issue command…"
          : "Type a command…",
    [isCalm, safeMode],
  );

  async function submit(raw) {
    const cmd = String(raw || "").trim();
    if (!cmd) return;
    const itemId = `u_${Date.now()}`;
    setIsSending(true);
    setHistory((prev) => [...prev, { id: itemId, role: "user", text: cmd }]);
    setInput("");
    try {
      const payload = await onSubmit?.(cmd);
      const result = normalizeSubmitResult(payload);

      if (isBrainExecutePayload(result)) {
        const { text, warn } = formatBrainExecuteResponse(result);
        const aid = `a_${Date.now()}`;
        setHistory((prev) => [
          ...prev,
          {
            id: aid,
            role: "assistant",
            text,
            blocks: null,
            tone: warn ? "warn" : "ok",
          },
        ]);
        setEnterAssistantId(aid);
        setTimeout(() => setEnterAssistantId(null), 520);
        return;
      }

      const ok = result?.ok !== false;
      const blocks = ok && Array.isArray(result?.blocks) && result.blocks.length ? result.blocks : null;
      const impact = result?.impact ? String(result.impact).trim() : "";
      const core = result?.message ? String(result.message).trim() : "Signal processed.";
      let assistantText = "";
      if (!blocks) {
        if (ok) {
          assistantText = impact ? `✔ Action executed\nImpact: ${impact}` : `✔ ${core}`;
        } else {
          assistantText = impact ? `${core}\n${impact}` : core;
        }
      }
      const aid = `a_${Date.now()}`;
      setHistory((prev) => [
        ...prev,
        {
          id: aid,
          role: "assistant",
          text: assistantText,
          blocks,
          tone: ok ? "ok" : "warn",
        },
      ]);
      setEnterAssistantId(aid);
      setTimeout(() => setEnterAssistantId(null), 520);
    } finally {
      setTimeout(() => setIsSending(false), 140);
    }
  }

  const shellClass = [
    isCalm
      ? "rounded-2xl border border-slate-800/80 bg-gradient-to-b from-slate-950/80 via-slate-950/80 to-slate-900/80 p-3 shadow-[0_1px_0_rgba(255,255,255,0.04),0_20px_50px_-24px_rgba(0,0,0,0.5)] backdrop-blur-md transition-[box-shadow,transform] duration-500 ease-out hover:shadow-[0_1px_0_rgba(255,255,255,0.05),0_24px_56px_-20px_rgba(59,130,246,0.12)]"
      : "rounded-2xl border border-slate-800 bg-slate-950/80 p-4",
    shellPulseClass ? "cc-shell-pulse" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const inputRowStyle = {
    position: "fixed",
    bottom: 0,
    left: 0,
    right: 0,
    width: "100%",
    maxWidth: "720px",
    margin: "0 auto",
    padding: "16px",
    background: "rgba(10,15,30,0.95)",
    backdropFilter: "blur(10px)",
    borderTop: "1px solid rgba(255,255,255,0.06)",
    zIndex: 40,
    boxSizing: "border-box",
  };

  const inputFieldStyle = {
    width: "100%",
    background: "rgba(255,255,255,0.06)",
    border: inputFocused ? "1px solid rgba(59,130,246,0.5)" : "1px solid rgba(255,255,255,0.12)",
    borderRadius: "10px",
    padding: "14px 16px",
    color: "#ffffff",
    fontSize: "15px",
    outline: "none",
    transition: "border-color 0.15s ease",
  };

  const sendBtnStyle = {
    background: "#3b82f6",
    color: "#ffffff",
    border: "none",
    borderRadius: "8px",
    padding: "10px 20px",
    fontSize: "14px",
    fontWeight: "600",
    cursor: "pointer",
    transition: "all 0.15s ease",
  };

  return (
    <section className={`${shellClass} relative pb-28`}>
      <div
        className={
          isCalm
            ? "rounded-xl border border-slate-800/80 bg-slate-900/80 p-3 ring-1 ring-white"
            : "rounded-xl border border-slate-700 bg-slate-900/80 p-3"
        }
      >
        <div
          className={`space-y-2 overflow-y-auto rounded-lg border border-slate-800/80 bg-slate-950/80 p-3 ${isCalm ? "max-h-56 min-h-[7rem]" : "max-h-48"}`}
          style={{ color: "#ffffff" }}
        >
          {history.slice(-6).map((h) => {
            const isEnter = h.role === "assistant" && h.id === enterAssistantId;
            const warnTone = h.role === "assistant" && h.tone === "warn";
            const blocks = h.role === "assistant" && Array.isArray(h.blocks) ? h.blocks : null;
            return (
              <div
                key={h.id}
                className={`rounded-xl px-3 py-2.5 text-sm leading-6 transition-[transform,background-color] duration-300 ease-out ${
                  h.role === "user"
                    ? "bg-sky-500/15 ring-1 ring-sky-400/15"
                    : warnTone
                      ? "bg-amber-500/10 ring-1 ring-amber-500/20"
                      : "bg-[rgba(255,255,255,0.05)] ring-1 ring-white/[0.06]"
                } ${isEnter ? "cc-msg-enter" : ""}`}
                style={{ color: "#ffffff" }}
              >
                {!isCalm ? (
                  <span
                    className="mr-2 uppercase tracking-[0.1em]"
                    style={{ color: "#ffffff", fontSize: "13px", fontWeight: "500" }}
                  >
                    {h.role}
                  </span>
                ) : null}
                {blocks ? (
                  <div className="space-y-2.5">
                    {blocks.map((b, bi) => {
                      const label =
                        b.kind === "signal"
                          ? "Signal"
                          : b.kind === "action"
                            ? "Action"
                            : b.kind === "outcome"
                              ? "Outcome"
                              : b.kind === "next"
                                ? "Next"
                                : "";
                      const bodyClass =
                        b.kind === "next"
                          ? "text-[13px] font-medium leading-6"
                          : b.kind === "outcome"
                            ? "text-[13px] leading-6"
                            : b.kind === "signal"
                              ? "text-[13px] leading-6"
                              : "text-[13px] leading-6";
                      return (
                        <div key={`${h.id}_b_${bi}`}>
                          <span
                            className="font-semibold uppercase tracking-[0.16em]"
                            style={{ color: "#ffffff", fontSize: "13px", fontWeight: "500" }}
                          >
                            {label}
                          </span>
                          <p className={`mt-0.5 ${bodyClass}`} style={{ color: "#ffffff" }}>
                            {b.text}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  h.text.split("\n").map((line, i) => (
                    <span
                      key={`${h.id}_ln_${i}`}
                      className={
                        i > 0
                          ? warnTone
                            ? "mt-1 block text-[13px] leading-6"
                            : "mt-1 block text-[13px] leading-6"
                          : "block leading-6"
                      }
                      style={{
                        color: warnTone && line.trimStart().startsWith("⚠️") ? "#fbbf24" : "#ffffff",
                      }}
                    >
                      {line}
                    </span>
                  ))
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div
        className={isCalm ? "flex items-center gap-2" : "flex gap-2 items-center"}
        style={inputRowStyle}
      >
        <input
          className={`flex-1 outline-none transition-[box-shadow,transform] duration-300 ease-out ${
            isCalm
              ? `${isSending ? "scale-[0.985]" : "scale-100"} focus:shadow-[0_0_0_3px_rgba(59,130,246,0.18)]`
              : `${isSending ? "scale-[0.99]" : "scale-100"}`
          }`}
          style={inputFieldStyle}
          placeholder={placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onFocus={() => setInputFocused(true)}
          onBlur={() => setInputFocused(false)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(input);
            }
          }}
        />
        <button
          type="button"
          className={`shrink-0 ${isCalm ? "py-3 text-sm" : "py-2 text-sm"}`}
          style={sendBtnStyle}
          onClick={() => submit(input)}
        >
          Send
        </button>
      </div>
    </section>
  );
}
