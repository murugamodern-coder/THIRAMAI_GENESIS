import { recordTelemetryForAlerts } from "./telemetryAlerts.js";

/**
 * Lightweight, non-blocking client telemetry.
 * logEvent(type, data) — microtask dispatch, never throws.
 *
 * Env:
 * - VITE_SENTRY_DSN — optional Sentry (lazy init on bootstrap)
 * - VITE_CC_SLOW_API_MS — slow threshold (default 2500)
 * - VITE_CC_TELEMETRY_NAV_SAMPLE / VITE_CC_TELEMETRY_ACTION_SAMPLE — 0..1 sampling
 * - VITE_CC_TELEMETRY_DEBUG=1 — verbose console (dev-style)
 * - VITE_CC_TELEMETRY_CONSOLE=1 — prod console for errors/slow only
 */

const isDev = typeof import.meta !== "undefined" && !!import.meta.env?.DEV;
const SLOW_API_MS = Number(
  typeof import.meta !== "undefined" ? import.meta.env?.VITE_CC_SLOW_API_MS ?? 2500 : 2500,
);
const NAV_SAMPLE = Number(
  typeof import.meta !== "undefined" ? import.meta.env?.VITE_CC_TELEMETRY_NAV_SAMPLE ?? (isDev ? 1 : 0.25) : 0.25,
);
const ACTION_SAMPLE = Number(
  typeof import.meta !== "undefined" ? import.meta.env?.VITE_CC_TELEMETRY_ACTION_SAMPLE ?? (isDev ? 1 : 0.2) : 0.2,
);

let sentryInitPromise = null;

function hasSentryDsn() {
  return typeof import.meta !== "undefined" && !!import.meta.env?.VITE_SENTRY_DSN;
}

function sample(rate) {
  if (rate >= 1) return true;
  if (rate <= 0) return false;
  return Math.random() < rate;
}

function scrub(obj) {
  if (obj == null || typeof obj !== "object") return obj;
  const deny = new Set([
    "password",
    "access_token",
    "refresh_token",
    "authorization",
    "Authorization",
    "token",
    "secret",
  ]);
  if (Array.isArray(obj)) {
    return obj.map((x) => scrub(x));
  }
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (deny.has(k)) {
      out[k] = "[redacted]";
      continue;
    }
    if (v instanceof Error) {
      out[k] = { name: v.name, message: v.message };
      continue;
    }
    out[k] = typeof v === "object" && v !== null ? scrub(v) : v;
  }
  return out;
}

export function redactUrl(url) {
  if (!url || typeof url !== "string") return url;
  try {
    const u = new URL(url, typeof window !== "undefined" ? window.location.origin : "http://local");
    u.searchParams.delete("token");
    u.searchParams.delete("access_token");
    return u.pathname + (u.search || "");
  } catch {
    return url.slice(0, 200);
  }
}

function shouldDebugConsole() {
  return typeof import.meta !== "undefined" && import.meta.env?.VITE_CC_TELEMETRY_DEBUG === "1";
}

function shouldErrorConsole() {
  return typeof import.meta !== "undefined" && import.meta.env?.VITE_CC_TELEMETRY_CONSOLE === "1";
}

function sentryAddBreadcrumb(entry) {
  if (!hasSentryDsn()) return;
  void import("@sentry/react")
    .then((Sentry) => {
      try {
        Sentry.addBreadcrumb({
          category: "telemetry",
          message: entry.type,
          level: entry.type === "api_error" ? "error" : "info",
          data: scrub({ ...entry }),
        });
      } catch {
        /* hub may not be ready yet */
      }
    })
    .catch(() => {});
}

function processEntry(entry) {
  try {
    if (isDev && shouldDebugConsole()) {
      console.debug("[cc:telemetry]", entry.type, entry);
    } else if (!isDev && shouldErrorConsole()) {
      if (entry.type === "ui_error" || entry.type === "api_error" || entry.type === "api_slow") {
        console.warn("[cc:telemetry]", entry.type, scrub(entry));
      }
    }

    if (entry.type === "api_error" || entry.type === "api_slow" || entry.type === "action") {
      sentryAddBreadcrumb(entry);
    }
    if (entry.type === "ui_error" || entry.type === "api_error") {
      recordTelemetryForAlerts(entry);
    }
  } catch {
    /* ignore */
  }
}

function ensureSentry() {
  if (!hasSentryDsn()) return;
  if (sentryInitPromise) return;
  sentryInitPromise = import("@sentry/react")
    .then((Sentry) => {
      Sentry.init({
        dsn: import.meta.env.VITE_SENTRY_DSN,
        environment: import.meta.env?.VITE_SENTRY_ENVIRONMENT || import.meta.env?.MODE || "production",
        integrations: [],
        tracesSampleRate: Number(import.meta.env?.VITE_SENTRY_TRACES_SAMPLE_RATE ?? 0),
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 0,
        sendDefaultPii: false,
        maxBreadcrumbs: 40,
        beforeBreadcrumb(breadcrumb) {
          if (breadcrumb?.category === "console") return null;
          return breadcrumb;
        },
        beforeSend(event) {
          try {
            if (event.request?.headers?.Authorization) {
              delete event.request.headers.Authorization;
            }
          } catch {
            /* ignore */
          }
          return event;
        },
      });
    })
    .catch(() => {
      sentryInitPromise = null;
    });
}

/**
 * @param {string} type page_view | page_load | api_success | api_error | api_slow | ui_error | action | perf_render
 * @param {Record<string, unknown>} [data]
 */
export function logEvent(type, data = {}) {
  if (typeof window === "undefined") return;
  if (type === "page_view" && !sample(NAV_SAMPLE)) return;
  if (type === "action" && !sample(ACTION_SAMPLE)) return;
  if (
    type === "perf_render" &&
    !isDev &&
    typeof import.meta !== "undefined" &&
    import.meta.env?.VITE_CC_PERF !== "1" &&
    !sample(0.12)
  ) {
    return;
  }
  if (type === "api_success") {
    const durationMs = data?.durationMs;
    if (
      durationMs != null &&
      durationMs < SLOW_API_MS &&
      !isDev &&
      typeof import.meta !== "undefined" &&
      import.meta.env?.VITE_CC_TELEMETRY_DEBUG !== "1"
    ) {
      return;
    }
  }
  const entry = { type, ts: Date.now(), ...scrub(data) };
  queueMicrotask(() => processEntry(entry));
}

export function reportAxiosSuccess(response) {
  const cfg = response?.config || {};
  const start = cfg.metadata?.start;
  const durationMs =
    start != null && typeof performance !== "undefined" ? Math.round(performance.now() - start) : undefined;
  const url = `${cfg.baseURL || ""}${cfg.url || ""}`;
  const method = String(cfg.method || "get").toUpperCase();
  const status = response?.status;
  if (durationMs != null && durationMs >= SLOW_API_MS) {
    logEvent("api_slow", { method, url: redactUrl(url), status, durationMs, ok: true });
    return;
  }
  logEvent("api_success", { method, url: redactUrl(url), status, durationMs, ok: true });
}

export function reportAxiosError(error) {
  const cfg = error?.config || {};
  const start = cfg.metadata?.start;
  const durationMs =
    start != null && typeof performance !== "undefined" ? Math.round(performance.now() - start) : undefined;
  const url = `${cfg.baseURL || ""}${cfg.url || ""}`;
  const method = String(cfg.method || "get").toUpperCase();
  const status = error?.response?.status ?? null;
  logEvent("api_error", {
    method,
    url: redactUrl(url),
    status,
    durationMs,
    code: error?.code || null,
    ok: false,
  });
  if (durationMs != null && durationMs >= SLOW_API_MS) {
    logEvent("api_slow", { method, url: redactUrl(url), status, durationMs, ok: false });
  }

  if (!hasSentryDsn()) return;
  const st = status;
  if (st == null || st >= 500 || error?.code === "ECONNABORTED" || error?.code === "ERR_NETWORK") {
    void import("@sentry/react")
      .then((Sentry) => {
        const err =
          error instanceof Error
            ? error
            : new Error(`api_error ${method} ${redactUrl(url)} ${st ?? ""}`.trim());
        Sentry.captureException(err, {
          tags: { http_status: String(st ?? "") },
          extra: scrub({ durationMs, code: error?.code }),
        });
      })
      .catch(() => {});
  }
}

export function captureUiError(error, context = {}) {
  logEvent(
    "ui_error",
    scrub({
      message: error?.message || String(error),
      boundary: context.boundary,
      failingComponent: context.failingComponent,
      componentStackHead: context.componentStackHead,
    }),
  );

  if (!hasSentryDsn()) return;
  void import("@sentry/react")
    .then((Sentry) => {
      const err = error instanceof Error ? error : new Error(String(error?.message || "ui_error"));
      Sentry.captureException(err, {
        tags: { boundary: String(context.boundary || "root") },
        extra: scrub({
          failingComponent: context.failingComponent,
          componentStackHead: context.componentStackHead,
        }),
      });
    })
    .catch(() => {});
}

export function trackCriticalAction(action, data = {}) {
  logEvent("action", { action, ...data });
}

let clickInstalled = false;

function installCriticalClickTracking() {
  if (typeof document === "undefined" || clickInstalled) return;
  clickInstalled = true;
  const handler = (e) => {
    const el = e.target?.closest?.("[data-cc-track]");
    if (!el) return;
    const action = el.getAttribute("data-cc-track");
    if (!action) return;
    trackCriticalAction(action, { tag: el.tagName });
  };
  document.addEventListener("click", handler, true);
}

export function initTelemetry() {
  queueMicrotask(() => {
    ensureSentry();
    installCriticalClickTracking();
    logEvent("page_load", { href: typeof window !== "undefined" ? window.location.href : "" });
  });
}
