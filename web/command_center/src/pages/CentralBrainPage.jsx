import { useEffect, useMemo, useRef, useState } from "react";
import api from "../api/client.js";

const SUGGESTIONS = [
  "📊 Stock analysis",
  "🔬 Research report",
  "📋 Business plan",
  "⚙️ System status",
];

function routeBadge(payload) {
  const r = String(payload?.routing || "").toUpperCase();
  if (r === "MISSION") return "→ Research OS";
  if (r === "ACTION") return "→ Action";
  return "→ Chat";
}

function routeKey(payload) {
  const r = String(payload?.routing || "").toUpperCase();
  if (r === "MISSION") return "MISSION";
  if (r === "ACTION") return "ACTION";
  return "CHAT";
}

export default function CentralBrainPage() {
  const [chat, setChat] = useState([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [proactiveAlerts, setProactiveAlerts] = useState([]);
  const [alertsOpen, setAlertsOpen] = useState(true);
  const [alertsDismissed, setAlertsDismissed] = useState(false);
  const listRef = useRef(null);

  const alertsCount = proactiveAlerts.length;

  useEffect(() => {
    let mounted = true;
    api.get("/api/brain/proactive").then((r) => {
      if (!mounted) return;
      setProactiveAlerts(Array.isArray(r.data?.alerts) ? r.data.alerts : []);
    }).catch(() => {
      if (!mounted) return;
      setProactiveAlerts([]);
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [chat, thinking]);

  useEffect(() => {
    const onUser = (ev) => {
      const content = String(ev?.detail?.content || "").trim();
      if (!content) return;
      setChat((prev) => [...prev, { role: "user", content, routing: "CHAT", timestamp: Date.now() }]);
      setThinking(true);
    };
    const onResponse = (ev) => {
      const payload = ev?.detail?.payload || {};
      const content = String(payload?.response || payload?.message || "").trim();
      if (!content) return;
      setChat((prev) => [...prev, { role: "thiramai", content, routing: routeKey(payload), timestamp: Date.now() }]);
      setThinking(false);
    };
    const onError = (ev) => {
      const content = String(ev?.detail?.error || "Command failed");
      setChat((prev) => [...prev, { role: "thiramai", content, routing: "CHAT", timestamp: Date.now() }]);
      setThinking(false);
    };
    window.addEventListener("thiramai-chat-user", onUser);
    window.addEventListener("thiramai-chat-response", onResponse);
    window.addEventListener("thiramai-chat-error", onError);
    return () => {
      window.removeEventListener("thiramai-chat-user", onUser);
      window.removeEventListener("thiramai-chat-response", onResponse);
      window.removeEventListener("thiramai-chat-error", onError);
    };
  }, []);

  async function submit(textOverride) {
    const command = String(textOverride ?? input).trim();
    if (!command || thinking) return;
    setInput("");
    setChat((prev) => [...prev, { role: "user", content: command, routing: "CHAT", timestamp: Date.now() }]);
    setThinking(true);
    try {
      const resp = await api.post("/api/orchestrator/command", { command, source: "central_brain_chat" });
      const payload = resp.data || {};
      setChat((prev) => [
        ...prev,
        {
          role: "thiramai",
          content: String(payload?.response || payload?.message || "Command accepted"),
          routing: routeKey(payload),
          timestamp: Date.now(),
        },
      ]);
    } catch (e) {
      setChat((prev) => [
        ...prev,
        { role: "thiramai", content: String(e?.response?.data?.detail || e?.message || "Command failed"), routing: "CHAT", timestamp: Date.now() },
      ]);
    } finally {
      setThinking(false);
    }
  }

  const visibleAlerts = useMemo(() => (alertsDismissed ? [] : proactiveAlerts), [alertsDismissed, proactiveAlerts]);

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "calc(100vh - 140px)", maxWidth: 800, margin: "0 auto", width: "100%" }}>
      <style>{`
        .cb-fade-in { animation: cbFadeIn .24s ease both; }
        @keyframes cbFadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        .cb-thinking-dot { animation: cbBlink 1s infinite; }
        .cb-thinking-dot:nth-child(2){ animation-delay:.2s; }
        .cb-thinking-dot:nth-child(3){ animation-delay:.4s; }
        @keyframes cbBlink { 0%,80%,100%{ opacity:.25 } 40%{ opacity:1 } }
      `}</style>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid var(--cc-border,#e5e7eb)", paddingBottom: 10, marginBottom: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 18 }}>🧠 THIRAMAI</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12 }}>
          <span style={{ color: "#1D9E75", fontWeight: 600 }}>● Live</span>
          <span style={{ color: "var(--cc-muted,#6b7280)" }}>[alerts: {alertsCount}]</span>
        </div>
      </div>

      {visibleAlerts.length > 0 ? (
        <div style={{ marginBottom: 10 }}>
          <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setAlertsOpen((v) => !v)}>
            {alertsOpen ? "Hide Alerts" : "Show Alerts"} ({visibleAlerts.length})
          </button>
          <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setAlertsDismissed(true)} style={{ marginLeft: 8 }}>
            Dismiss
          </button>
          {alertsOpen ? (
            <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
              {visibleAlerts.map((a, i) => {
                const critical = String(a?.severity || "").toLowerCase() === "critical";
                return (
                  <div key={`${a?.type || "alert"}_${i}`} style={{ padding: "8px 10px", borderRadius: 10, fontSize: 12, border: `1px solid ${critical ? "#DC2626" : "#D97706"}`, background: critical ? "#FEE2E2" : "#FEF3C7" }}>
                    <strong>{String(a?.type || "alert").toUpperCase()}</strong> — {a?.message}
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      <div ref={listRef} style={{ flex: 1, overflowY: "auto", paddingBottom: 12 }}>
        {chat.length === 0 ? (
          <div style={{ minHeight: 320, display: "grid", placeItems: "center", textAlign: "center", color: "var(--cc-muted,#6b7280)", padding: 20 }}>
            <div>
              <div style={{ fontSize: 44, marginBottom: 8 }}>⚡</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "var(--cc-text,#111827)" }}>நான் Thiramai — உங்கள் Sovereign AI</div>
              <div style={{ marginTop: 8 }}>Personal · Business · Stock · Research · Agentic</div>
              <div style={{ marginTop: 14, display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="cc-btn cc-btn-secondary" onClick={() => submit(s)}>
                    {s}
                  </button>
                ))}
              </div>
              <div style={{ marginTop: 12, fontSize: 13 }}>நான் Thiramai. என்ன செய்யட்டும்?</div>
            </div>
          </div>
        ) : (
          chat.map((m, idx) => {
            const user = m.role === "user";
            return (
              <div key={`${m.timestamp}_${idx}`} className="cb-fade-in" style={{ display: "flex", justifyContent: user ? "flex-end" : "flex-start", marginBottom: 10 }}>
                <div style={{ maxWidth: "82%", background: user ? "#2563EB" : "#111827", color: "#fff", borderRadius: 14, padding: "10px 12px" }}>
                  <div style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>{m.content}</div>
                  <div style={{ marginTop: 6, opacity: 0.8, fontSize: 11, display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <span>{user ? "You" : routeBadge({ routing: m.routing })}</span>
                    <span>{new Date(m.timestamp).toLocaleTimeString()}</span>
                  </div>
                </div>
              </div>
            );
          })
        )}

        {thinking ? (
          <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 10 }}>
            <div style={{ background: "#111827", color: "#fff", borderRadius: 14, padding: "10px 12px", fontSize: 14 }}>
              Thiramai is thinking
              <span className="cb-thinking-dot">.</span>
              <span className="cb-thinking-dot">.</span>
              <span className="cb-thinking-dot">.</span>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ position: "sticky", bottom: 0, background: "var(--cc-bg,#fff)", paddingTop: 8 }}>
        <div style={{ display: "flex", gap: 8, border: "1px solid var(--cc-border,#e5e7eb)", borderRadius: 14, padding: 8, background: "var(--cc-surface,#fff)" }}>
          <span style={{ fontSize: 18, lineHeight: "38px" }}>⚡</span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder="Type command or /"
            style={{ flex: 1, border: "none", outline: "none", background: "transparent", minHeight: 42 }}
          />
          <button type="button" className="cc-btn cc-btn-primary" onClick={() => submit()} disabled={thinking}>
            {thinking ? "..." : "Run →"}
          </button>
        </div>
      </div>
    </div>
  );
}
