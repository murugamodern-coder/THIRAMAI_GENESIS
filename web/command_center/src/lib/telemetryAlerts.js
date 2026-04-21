/**
 * Lightweight spike detection for ui_error / api_error — integrates with telemetry.
 * Optional webhook: VITE_CC_ALERT_WEBHOOK (POST JSON, fire-and-forget).
 */

const WINDOW_MS = 60_000;
const UI_THRESHOLD = 5;
const API_THRESHOLD = 12;
const COOLDOWN_MS = 5 * 60_000;

const buffer = [];
let lastAlertAt = 0;

function prune(now) {
  const cutoff = now - WINDOW_MS;
  while (buffer.length && buffer[0].t < cutoff) {
    buffer.shift();
  }
}

function postWebhook(payload) {
  const url = typeof import.meta !== "undefined" ? import.meta.env?.VITE_CC_ALERT_WEBHOOK : "";
  if (!url || typeof fetch === "undefined") return;
  try {
    void fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    });
  } catch {
    /* ignore */
  }
}

/**
 * Record telemetry entry for spike analysis (call from telemetry pipeline).
 * @param {{ type: string, ts?: number }} entry
 */
export function recordTelemetryForAlerts(entry) {
  if (entry.type !== "ui_error" && entry.type !== "api_error") return;
  const now = entry.ts || Date.now();
  prune(now);
  buffer.push({ type: entry.type, t: now });

  const ui = buffer.filter((x) => x.type === "ui_error").length;
  const api = buffer.filter((x) => x.type === "api_error").length;

  if (now - lastAlertAt < COOLDOWN_MS) return;
  if (ui < UI_THRESHOLD && api < API_THRESHOLD) return;

  lastAlertAt = now;
  const payload = {
    kind: "telemetry_spike",
    at: new Date(now).toISOString(),
    windowMs: WINDOW_MS,
    ui_errors: ui,
    api_errors: api,
    thresholds: { ui: UI_THRESHOLD, api: API_THRESHOLD },
  };

  postWebhook(payload);

  void import("./telemetry.js")
    .then((m) => m.logEvent("alert_spike", payload))
    .catch(() => {});

  if (typeof import.meta !== "undefined" && import.meta.env?.VITE_CC_TELEMETRY_DEBUG === "1") {
    console.warn("[cc:alert]", payload);
  }
}
