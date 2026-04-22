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
  const recognitionRef = useRef(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);
  const [attachment, setAttachment] = useState(null);
  const [listening, setListening] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

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
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 140);
    el.style.height = `${Math.max(24, next)}px`;
  }, [value]);

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
  });

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
      if (transcript.trim()) setValue((prev) => `${prev}${prev ? " " : ""}${transcript.trim()}`);
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
    <div className="cc-global-command">
      {attachment ? (
        <div className="cc-attachment-preview">
          {attachment.preview ? (
            <div className="cc-attachment-thumb-wrap">
              <img src={attachment.preview} alt={attachment.name} className="cc-attachment-thumb" />
              <button type="button" className="cc-attachment-remove" onClick={() => setAttachment(null)}>×</button>
            </div>
          ) : (
            <div className="cc-attachment-pill">
              <span>📄 {attachment.name}</span>
              <button type="button" className="cc-attachment-remove-inline" onClick={() => setAttachment(null)}>×</button>
            </div>
          )}
        </div>
      ) : null}

      <div className="cc-command-pill">
        <button type="button" className="cc-command-icon" disabled={busy} onClick={() => fileInputRef.current?.click()} title="Attach file">
          📎
        </button>
        <button type="button" className="cc-command-icon" disabled={busy} onClick={toggleVoice} title="Voice (Chrome only)">
          🎤
        </button>
        {isMobile ? (
          <button type="button" className="cc-command-icon" disabled={busy} onClick={() => cameraInputRef.current?.click()} title="Camera">
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
          placeholder="Thiramai-கிட்ட கேளு... (/ or Cmd+K)"
          className="cc-command-textarea"
          disabled={busy}
          rows={1}
        />
        <button onClick={submit} disabled={busy} className="cc-command-run">
          {busy ? "..." : "Run →"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,.pdf,.txt,.csv,.xlsx"
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
        <div className={`cc-command-hint ${errorMsg ? "error" : ""}`}>
          {errorMsg || <><span className="cc-listening-dot" /> Listening...</>}
        </div>
      ) : null}

      {open && result ? (
        <div className="cc-global-command-result">
          <span className="cc-command-route-badge" style={{ color: badge.color, borderColor: `${badge.color}60`, background: `${badge.color}15` }}>
            → Routed to {badge.label}
          </span>
          <div>
            {result?.error
              ? `Error: ${result.error}`
              : result?.show_inline
                ? String(result?.response || "No response available")
                : result?.task_id
                  ? `Mission ${result.task_id} created${result?.requires_approval ? " · approval required" : ""}`
                  : String(result?.message || "Command accepted")}
          </div>
        </div>
      ) : null}
    </div>
  );
}
