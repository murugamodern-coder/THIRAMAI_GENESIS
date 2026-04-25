import { useEffect, useMemo, useRef, useState } from "react";

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
      const result = await onSubmit?.(cmd);
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

  return (
    <section className={shellClass}>
      <div
        className={
          isCalm
            ? "rounded-xl border border-slate-800/80 bg-slate-900/80 p-3 ring-1 ring-white"
            : "rounded-xl border border-slate-700 bg-slate-900/80 p-3"
        }
      >
        <div
          className={`space-y-2 overflow-y-auto rounded-lg border border-slate-800/80 bg-slate-950/80 p-3 ${isCalm ? "max-h-56 min-h-[7rem]" : "max-h-48"}`}
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
                    ? "bg-sky-500/15 text-sky-50 ring-1 ring-sky-400/15"
                    : warnTone
                      ? "bg-amber-500/10 text-amber-50 ring-1 ring-amber-500/20"
                      : "bg-[rgba(255,255,255,0.05)] text-[#e2e8f0] ring-1 ring-white/[0.06]"
                } ${isEnter ? "cc-msg-enter" : ""}`}
              >
                {!isCalm ? (
                  <span className="mr-2 text-[10px] uppercase tracking-[0.1em] text-white">{h.role}</span>
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
                          ? "text-[13px] font-medium leading-6 text-emerald-100"
                          : b.kind === "outcome"
                            ? "text-[13px] leading-6 text-slate-100"
                            : b.kind === "signal"
                              ? "text-[13px] leading-6 text-white"
                              : "text-[13px] leading-6 text-[#e2e8f0]";
                      return (
                        <div key={`${h.id}_b_${bi}`}>
                          <span className="text-[9px] font-semibold uppercase tracking-[0.16em] text-white">
                            {label}
                          </span>
                          <p className={`mt-0.5 ${bodyClass}`}>{b.text}</p>
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
                            ? "mt-1 block text-[13px] leading-6 text-amber-100"
                            : "mt-1 block text-[13px] leading-6 text-emerald-100"
                          : "block leading-6"
                      }
                    >
                      {line}
                    </span>
                  ))
                )}
              </div>
            );
          })}
        </div>
        <div className={`mt-3 flex gap-2 ${isCalm ? "items-center" : ""}`}>
          <input
            className={`flex-1 rounded-xl border bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none transition-[border-color,box-shadow,transform] duration-300 ease-out placeholder:text-slate-200 focus:border-slate-200 ${
              isCalm
                ? `border-slate-800 py-3 focus:shadow-[0_0_0_3px_rgba(59,130,246,0.18)] ${isSending ? "scale-[0.985]" : "scale-100"}`
                : `border-slate-700 py-2 ${isSending ? "scale-[0.99]" : "scale-100"}`
            }`}
            placeholder={placeholder}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(input);
              }
            }}
          />
          <button
            type="button"
            className={`shrink-0 rounded-xl bg-gradient-to-b from-white to-slate-200 px-5 font-semibold text-slate-900 shadow-[0_1px_0_rgba(255,255,255,0.5)] transition-all duration-300 ease-out hover:-translate-y-0.5 hover:shadow-[0_8px_24px_-6px_rgba(255,255,255,0.25)] active:scale-[0.97] active:translate-y-0 ${isCalm ? "py-3 text-sm" : "py-2 text-sm"}`}
            onClick={() => submit(input)}
          >
            Send
          </button>
        </div>
      </div>
    </section>
  );
}
