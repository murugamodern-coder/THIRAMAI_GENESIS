import { useEffect, useMemo, useRef, useState } from "react";
import api from "../api/client.js";
import { showToastDedup } from "../lib/toastDedup.js";

const SUGGESTIONS = [
  "📊 Stock analysis",
  "🔬 Research report",
  "📋 Business plan",
  "⚙️ System status",
];

function routeBadge(payload) {
  const r = String(payload?.routing || "").toUpperCase();
  if (r === "MISSION") return "🔬 Research OS";
  if (r === "ACTION") return "⚡ Agentic OS";
  return "🧠 Chat";
}

function routeKey(payload) {
  const r = String(payload?.routing || "").toUpperCase();
  if (r === "MISSION") return "MISSION";
  if (r === "ACTION") return "ACTION";
  return "CHAT";
}

export default function CentralBrainPage() {
  const [chat, setChat] = useState([]);
  const [morningBrief, setMorningBrief] = useState(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [proactiveAlerts, setProactiveAlerts] = useState([]);
  const [alertsOpen, setAlertsOpen] = useState(true);
  const [alertsDismissed, setAlertsDismissed] = useState(false);
  const [expandedByIndex, setExpandedByIndex] = useState({});
  const [copiedByIndex, setCopiedByIndex] = useState({});
  const listRef = useRef(null);
  const messagesEndRef = useRef(null);

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
    let mounted = true;
    api
      .get("/api/brain/morning-brief")
      .then((r) => {
        if (!mounted) return;
        const brief = String(r.data?.brief || "").trim();
        if (brief) {
          setMorningBrief({ text: brief, generatedAt: r.data?.generated_at || "" });
        }
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    let mounted = true;
    api
      .get("/api/brain/history")
      .then((r) => {
        if (!mounted) return;
        const rows = Array.isArray(r.data?.messages) ? r.data.messages : [];
        if (rows.length > 0) {
          setChat(
            rows.map((m) => ({
              role: m.role === "user" ? "user" : "thiramai",
              content: String(m.content || ""),
              routing: m.routing || "CHAT",
              timestamp: m.timestamp ? Date.parse(m.timestamp) || Date.now() : Date.now(),
            })),
          );
        }
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
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

  function triggerGlobalCommand(text) {
    const command = String(text || "").trim();
    if (!command || thinking) return;
    window.dispatchEvent(new CustomEvent("thiramai-command-request", { detail: { command, source: "central_brain_suggestion" } }));
  }

  const visibleAlerts = useMemo(() => (alertsDismissed ? [] : proactiveAlerts), [alertsDismissed, proactiveAlerts]);

  return (
    <div className="cb-page">
      <div className="cb-topbar">
        <div className="cb-title">🧠 THIRAMAI</div>
        <div className="cb-status">
          <span className="cb-live">● Live</span>
          <button
            type="button"
            className="cc-btn cc-btn-ghost cb-clear-chat"
            title="Clear chat"
            aria-label="Clear chat history"
            onClick={async () => {
              try {
                await api.delete("/api/brain/history");
                setChat([]);
              } catch {
                showToastDedup({ type: "error", message: "Could not clear chat history" });
              }
            }}
          >
            🗑️
          </button>
          <span>[alerts: {alertsCount}]</span>
        </div>
      </div>

      {visibleAlerts.length > 0 ? (
        <div className="cb-alert-wrap">
          <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setAlertsOpen((v) => !v)}>
            {alertsOpen ? "Hide Alerts" : "Show Alerts"} ({visibleAlerts.length})
          </button>
          <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setAlertsDismissed(true)}>
            Dismiss
          </button>
          {alertsOpen ? (
            <div className="cb-alert-grid">
              {visibleAlerts.map((a, i) => {
                const critical = String(a?.severity || "").toLowerCase() === "critical";
                return (
                  <div
                    key={`${a?.type || "alert"}_${i}`}
                    className={`cb-alert-item ${critical ? "critical" : "warning"}`}
                  >
                    <strong>{String(a?.type || "alert").toUpperCase()}</strong> — {a?.message}
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}

      <div ref={listRef} className="cb-message-container">
        {chat.length === 0 ? (
          <div className="cb-welcome">
            {morningBrief ? (
              <div className="cb-morning-brief">
                <button
                  type="button"
                  className="cb-morning-brief__toggle"
                  onClick={() => setBriefOpen((v) => !v)}
                  aria-expanded={briefOpen}
                >
                  <span>🌅 Morning brief</span>
                  <span className="cb-morning-brief__chev">{briefOpen ? "▼" : "▶"}</span>
                </button>
                {briefOpen ? (
                  <div className="cb-morning-brief__body">
                    <div className="cb-morning-brief__text">{morningBrief.text}</div>
                    {morningBrief.generatedAt ? (
                      <div className="cb-morning-brief__meta">{new Date(morningBrief.generatedAt).toLocaleString()}</div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="cb-welcome-icon">⚡</div>
            <div className="cb-welcome-title">நான் Thiramai</div>
            <div className="cb-welcome-subtitle">உங்கள் Sovereign AI Assistant</div>
            <div className="cb-welcome-subtitle">Personal · Business · Stock · Research · Agentic</div>
            <div className="cb-suggestion-grid">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" className="cb-suggestion-chip" onClick={() => triggerGlobalCommand(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          chat.map((m, idx) => {
            const user = m.role === "user";
            const words = String(m.content || "").trim().split(/\s+/).filter(Boolean);
            const shouldClamp = words.length > 500;
            const expanded = !!expandedByIndex[idx];
            const displayText = shouldClamp && !expanded ? `${words.slice(0, 500).join(" ")}...` : m.content;

            return (
              <div key={`${m.timestamp}_${idx}`} className={`cb-message-row ${user ? "user" : "bot"}`}>
                {!user ? <div className="cb-routing-badge">{routeBadge({ routing: m.routing })}</div> : null}
                <div className={`cb-bubble ${user ? "user" : "bot"}`}>
                  <div>{displayText}</div>
                  {shouldClamp ? (
                    <button
                      type="button"
                      className="cb-toggle"
                      onClick={() => setExpandedByIndex((prev) => ({ ...prev, [idx]: !expanded }))}
                    >
                      {expanded ? "Show less" : "Show more"}
                    </button>
                  ) : null}
                  <div className="cb-meta">
                    <span>{new Date(m.timestamp).toLocaleTimeString()}</span>
                    {!user ? (
                      null
                    ) : null}
                  </div>
                </div>
                {!user ? (
                  <div className="cb-action-bar">
                    <button
                      type="button"
                      className="cb-copy-action"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(String(m.content || ""));
                          setCopiedByIndex((prev) => ({ ...prev, [idx]: true }));
                          showToastDedup({ type: "success", message: "Copied!" });
                          setTimeout(() => {
                            setCopiedByIndex((prev) => ({ ...prev, [idx]: false }));
                          }, 2000);
                        } catch {
                          showToastDedup({ type: "error", message: "Copy failed" });
                        }
                      }}
                    >
                      {copiedByIndex[idx] ? "✓ Copied" : "📋 Copy"}
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })
        )}

        {thinking ? (
          <div className="cb-message-row bot">
            <div className="cb-bubble bot cb-thinking">
              Thiramai is thinking
              <span className="cb-thinking-dot">.</span>
              <span className="cb-thinking-dot">.</span>
              <span className="cb-thinking-dot">.</span>
            </div>
          </div>
        ) : null}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
