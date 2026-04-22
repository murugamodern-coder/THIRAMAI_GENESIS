import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/client.js";
import { showToastDedup } from "../lib/toastDedup.js";

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
  const fileInputRef = useRef(null);
  const cameraInputRef = useRef(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);
  const [attachment, setAttachment] = useState(null);
  const [listening, setListening] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const recognitionRef = useRef(null);

  const isMobile = useMemo(() => window.matchMedia?.("(max-width: 768px)")?.matches, []);
  const MAX_SIZE = 10 * 1024 * 1024;

  async function fileToDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  async function addFiles(list) {
    const files = Array.from(list || []);
    if (!files.length) return;
    const file = files[0];
    if (file.size > MAX_SIZE) {
      const msg = `${file.name} exceeds 10MB limit`;
      setErrorMsg(msg);
      showToastDedup({ type: "error", message: msg });
      return;
    }
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    const isImage = file.type.startsWith("image/");
    const allowed = isImage || ["pdf", "txt", "csv", "xlsx"].includes(ext);
    if (!allowed) {
      const msg = `Unsupported file type: ${file.name}`;
      setErrorMsg(msg);
      showToastDedup({ type: "error", message: msg });
      return;
    }
    const dataUrl = await fileToDataUrl(file);
    const base64 = dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;
    setAttachment({
      name: file.name,
      type: file.type || `application/${ext}`,
      data: base64,
      preview: isImage ? dataUrl : "",
    });
    setErrorMsg("");
    setOpen(true);
  }

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

  useEffect(() => {
    const onDrop = async (e) => {
      if (!e.dataTransfer?.files?.length) return;
      e.preventDefault();
      e.stopPropagation();
      await addFiles(e.dataTransfer.files);
    };
    const onDragOver = (e) => {
      if (e.dataTransfer?.types?.includes("Files")) e.preventDefault();
    };
    const onPaste = async (e) => {
      if (!e.clipboardData?.items?.length) return;
      const pastedFiles = [];
      for (const item of e.clipboardData.items) {
        if (item.kind === "file") {
          const f = item.getAsFile();
          if (f) pastedFiles.push(f);
        }
      }
      if (pastedFiles.length) await addFiles(pastedFiles);
    };
    window.addEventListener("drop", onDrop);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("paste", onPaste);
    return () => {
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("paste", onPaste);
    };
  }, []);

  useEffect(() => {
    const onCommandRequest = (ev) => {
      const command = String(ev?.detail?.command || "").trim();
      if (!command || busy) return;
      executeSubmit(command, ev?.detail?.source || "external_event");
    };
    window.addEventListener("thiramai-command-request", onCommandRequest);
    return () => window.removeEventListener("thiramai-command-request", onCommandRequest);
  }, [busy]);

  function stopVoice() {
    try {
      recognitionRef.current?.stop();
    } catch {
      // ignore
    }
    setListening(false);
  }

  function toggleVoice() {
    if (listening) {
      stopVoice();
      return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      const msg = "Voice not supported in this browser";
      setErrorMsg(msg);
      showToastDedup({ type: "warning", message: msg });
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = "ta-IN";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onstart = () => {
      setListening(true);
      setErrorMsg("");
    };
    recognition.onresult = (e) => {
      const transcript = e?.results?.[0]?.[0]?.transcript || "";
      if (transcript.trim()) setValue(transcript);
    };
    recognition.onerror = (e) => {
      setListening(false);
      const msg = `Mic error: ${e?.error || "unknown"}`;
      setErrorMsg(msg);
      showToastDedup({ type: "error", message: msg });
    };
    recognition.onend = () => {
      setListening(false);
    };
    recognitionRef.current = recognition;
    recognition.start();
  }

  async function executeSubmit(forcedCommand, source = "global_bar") {
    const command = String(forcedCommand ?? value).trim();
    if (!command || busy) return;
    window.dispatchEvent(new CustomEvent("thiramai-chat-user", { detail: { content: command } }));
    setBusy(true);
    setErrorMsg("");
    setValue("");
    setResult(null);
    try {
      const resp = await api.post("/api/orchestrator/command", {
        command,
        source,
        attachment: attachment
          ? { name: attachment.name, type: attachment.type, data: attachment.data }
          : undefined,
      });
      const payload = resp.data || { message: "Command accepted" };
      setResult(payload);
      setAttachment(null);
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
      setErrorMsg(String(error));
      window.dispatchEvent(new CustomEvent("thiramai-chat-error", { detail: { error } }));
    } finally {
      setBusy(false);
    }
  }

  function submit() {
    executeSubmit(value, "global_bar");
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
        {attachment ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 8 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center", background: "rgba(15,23,42,0.06)", borderRadius: 8, padding: "4px 8px", fontSize: 12 }}>
              {attachment.preview ? <img src={attachment.preview} alt={attachment.name} style={{ width: 26, height: 26, objectFit: "cover", borderRadius: 6 }} /> : <span>📄</span>}
              <span>{attachment.name}</span>
              <button type="button" className="cc-btn cc-btn-ghost" onClick={() => setAttachment(null)}>×</button>
            </div>
          </div>
        ) : null}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button type="button" className="cc-btn cc-btn-ghost" disabled={busy} onClick={() => fileInputRef.current?.click()} title="Attach file" style={{ width: 36, height: 36, padding: 0, flexShrink: 0 }}>
            📎
          </button>
          <button type="button" className="cc-btn cc-btn-ghost" disabled={busy} onClick={toggleVoice} title="Voice (Chrome only)" style={{ width: 36, height: 36, padding: 0, flexShrink: 0 }}>
            🎤
            {listening ? <span style={{ width: 8, height: 8, marginLeft: 6, borderRadius: "50%", display: "inline-block", background: "#ef4444", boxShadow: "0 0 0 0 rgba(239,68,68,0.8)", animation: "cbPulse 1s infinite" }} /> : null}
          </button>
          {isMobile ? (
            <button type="button" className="cc-btn cc-btn-ghost" disabled={busy} onClick={() => cameraInputRef.current?.click()} title="Camera" style={{ width: 36, height: 36, padding: 0, flexShrink: 0 }}>
              📷
            </button>
          ) : null}
          <textarea
            ref={inputRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
              if (e.key === "Escape") setOpen(false);
            }}
            placeholder="Command Thiramai... (/ or Cmd+K)"
            style={{
              flex: 1, border: "none", background: "transparent",
              outline: "none", fontSize: "14px", color: "#1a1a1a", resize: "none", minHeight: 40, maxHeight: 120, minWidth: 0,
            }}
            disabled={busy}
          />
          <button
            onClick={submit}
            disabled={busy}
            style={{
              background: busy ? "#94a3b8" : "#0f172a", color: "#fff",
              border: "none", borderRadius: "10px", padding: "7px 18px",
              fontSize: "13px", fontWeight: 500, cursor: busy ? "not-allowed" : "pointer", flexShrink: 0,
            }}
          >
            {busy ? "..." : "Run →"}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf,.txt,.csv,.xlsx"
            multiple
            style={{ display: "none" }}
            onChange={async (e) => {
              await addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: "none" }}
            onChange={async (e) => {
              await addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
        {(listening || errorMsg) ? (
          <div style={{ marginTop: 8, fontSize: 12, color: errorMsg ? "#b91c1c" : "#1d4ed8" }}>
            {errorMsg || "Listening..."}
          </div>
        ) : null}
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
      <style>{`
        @keyframes cbPulse {
          0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.8); }
          70% { box-shadow: 0 0 0 8px rgba(239,68,68,0); }
          100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
        }
      `}</style>
    </div>
  );
}
