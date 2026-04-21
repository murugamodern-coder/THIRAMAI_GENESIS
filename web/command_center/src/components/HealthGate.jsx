import { useCallback, useEffect, useState } from "react";

import { logEvent } from "../lib/telemetry.js";

function healthBaseUrl() {
  try {
    if (typeof import.meta !== "undefined" && import.meta.env?.VITE_CC_HEALTH_ORIGIN) {
      return String(import.meta.env.VITE_CC_HEALTH_ORIGIN).replace(/\/$/, "");
    }
  } catch {
    /* ignore */
  }
  return "";
}

async function fetchJson(path, timeoutMs) {
  const base = healthBaseUrl();
  const url = `${base}${path}`;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctrl.signal, credentials: "same-origin" });
    return { ok: r.ok, status: r.status };
  } finally {
    clearTimeout(t);
  }
}

function shouldRunGate() {
  try {
    if (typeof import.meta === "undefined") return false;
    if (import.meta.env?.VITE_CC_SKIP_HEALTH_GATE === "1") return false;
    if (import.meta.env.DEV && import.meta.env?.VITE_CC_ENABLE_HEALTH_GATE !== "1") return false;
    return true;
  } catch {
    return false;
  }
}

/**
 * Blocks main UI until /health/live (and optionally /health/ready) return 200.
 * Dev: off unless VITE_CC_ENABLE_HEALTH_GATE=1. Prod: on unless VITE_CC_SKIP_HEALTH_GATE=1.
 */
export default function HealthGate({ children }) {
  const [state, setState] = useState(() => (shouldRunGate() ? "checking" : "ok"));

  const run = useCallback(async () => {
    if (!shouldRunGate()) {
      setState("ok");
      return;
    }
    setState("checking");
    try {
      const live = await fetchJson("/health/live", 8000);
      if (!live.ok) {
        setState("fail");
        logEvent("health_check_fail", { phase: "live", status: live.status });
        return;
      }
      const ready = await fetchJson("/health/ready", 15000);
      if (!ready.ok) {
        setState("degraded");
        logEvent("health_check_fail", { phase: "ready", status: ready.status });
        return;
      }
      setState("ok");
      logEvent("health_check_ok", {});
    } catch {
      setState("fail");
      logEvent("health_check_fail", { phase: "network" });
    }
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  if (state === "ok") {
    return children;
  }

  if (state === "checking") {
    return (
      <div className="cc-card" style={{ maxWidth: 480, margin: "48px auto", padding: 24 }}>
        <h2 style={{ marginTop: 0 }}>Checking service…</h2>
        <p className="cc-muted">Verifying API health before loading the app.</p>
      </div>
    );
  }

  const degraded = state === "degraded";

  return (
    <div className="cc-card" style={{ maxWidth: 520, margin: "48px auto", padding: 24 }} role="alert">
      <h2 style={{ marginTop: 0 }}>{degraded ? "Service degraded" : "Service unavailable"}</h2>
      <p className="cc-muted">
        {degraded
          ? "The API is live but readiness checks failed (database, workers, or dependencies). You can retry or continue with limited functionality."
          : "Could not reach the API health endpoints. Check your network or try again shortly."}
      </p>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 16 }}>
        <button type="button" className="cc-btn cc-btn-primary" onClick={() => void run()}>
          Retry
        </button>
        {degraded ? (
          <button type="button" className="cc-btn cc-btn-secondary" onClick={() => setState("ok")}>
            Continue anyway
          </button>
        ) : null}
      </div>
    </div>
  );
}
