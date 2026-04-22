import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client.js";

const OS_BADGE = {
  stock: { label: "Stock OS", color: "#f59e0b" },
  research: { label: "Research OS", color: "#f97316" },
  business: { label: "Business OS", color: "#3b82f6" },
  personal: { label: "Personal OS", color: "#10b981" },
  agentic: { label: "Agentic OS", color: "#a855f7" },
};

function inferOsKey(payload) {
  const direct = payload?.os_key || payload?.handled_by || payload?.os;
  if (typeof direct === "string" && direct.trim()) return direct.trim().toLowerCase();
  const text = String(payload?.message || payload?.detail || "").toLowerCase();
  if (text.includes("stock") || text.includes("trade") || text.includes("nifty")) return "stock";
  if (text.includes("research") || text.includes("news")) return "research";
  if (text.includes("business") || text.includes("gst")) return "business";
  if (text.includes("personal") || text.includes("calendar")) return "personal";
  return "agentic";
}

export default function GlobalCommandBar() {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    const onKey = (e) => {
      const isModK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      const isSlash = e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey;
      if (isModK || isSlash) {
        const tag = document.activeElement?.tagName?.toLowerCase();
        if (isSlash && (tag === "input" || tag === "textarea")) return;
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 50);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function submit() {
    const command = value.trim();
    if (!command || busy) return;
    window.dispatchEvent(new CustomEvent("thiramai-chat-user", { detail: { content: command } }));
    setValue("");
    setBusy(true);
    setResult(null);
    try {
      const resp = await api.post("/api/orchestrator/command", { command, source: "global_bar" });
      const payload = resp.data || { message: "Command accepted" };
      setResult(payload);
      window.dispatchEvent(new CustomEvent("thiramai-chat-response", { detail: { payload } }));
      if (!payload?.show_inline) {
        const routedOs = inferOsKey(payload);
        const nextRoute = routedOs === "stock"
          ? "/os/stock"
          : routedOs === "research"
            ? "/os/research"
            : routedOs === "business"
              ? "/dashboard/inventory"
              : routedOs === "personal"
                ? "/personal"
                : "/os/agentic-platform";
        navigate(nextRoute);
      }
    } catch (err) {
      const error = err?.response?.data?.detail || err?.message || "Command failed";
      setResult({ error });
      window.dispatchEvent(new CustomEvent("thiramai-chat-error", { detail: { error } }));
    } finally {
      setBusy(false);
    }
  }

  const osKey = result ? inferOsKey(result) : "agentic";
  const badge = OS_BADGE[osKey] || OS_BADGE.agentic;

  return (
    <div
      className="cc-global-command"
      style={{
      position: "fixed", bottom: "20px", left: "50%", transform: "translateX(-50%)",
      width: "min(720px, calc(100vw - 32px))", zIndex: 1200,
      }}
    >
      <div style={{
        background: "rgba(255,255,255,0.85)", backdropFilter: "blur(12px)",
        border: "1px solid rgba(0,0,0,0.12)", borderRadius: "16px",
        padding: "10px 12px", boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
      }}>
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <span style={{ fontSize: "16px", opacity: 0.5 }}>⚡</span>
          <input
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
              if (e.key === "Escape") setOpen(false);
            }}
            placeholder="Command Thiramai... (/ or Cmd+K)"
            style={{
              flex: 1, border: "none", background: "transparent",
              outline: "none", fontSize: "14px", color: "#1a1a1a",
            }}
          />
          <button
            onClick={submit}
            disabled={busy}
            style={{
              background: busy ? "#94a3b8" : "#0f172a", color: "#fff",
              border: "none", borderRadius: "10px", padding: "7px 18px",
              fontSize: "13px", fontWeight: 500, cursor: busy ? "not-allowed" : "pointer",
            }}
          >
            {busy ? "..." : "Run →"}
          </button>
        </div>
        {open && result && (
          <div className="cc-global-command-result" style={{
            marginTop: "10px", padding: "10px 12px",
            background: "rgba(0,0,0,0.04)", borderRadius: "10px", fontSize: "13px",
          }}>
            <span style={{
              display: "inline-block", padding: "2px 10px", borderRadius: "20px",
              background: badge.color + "22", color: badge.color,
              fontWeight: 600, marginBottom: "6px", fontSize: "12px",
            }}>
              → Routed to {badge.label}
            </span>
            <div style={{ color: "#374151" }}>
              {result?.error
                ? `Error: ${result.error}`
                : result?.show_inline
                  ? String(result?.response || "No response available")
                : result?.task_id
                  ? `Mission ${result.task_id} created${result?.requires_approval ? " · approval required" : ""}`
                  : String(result?.message || "Command accepted")}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
