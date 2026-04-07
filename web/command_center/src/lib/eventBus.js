const listeners = new Map();
const lastPublishedAt = new Map();
const DEFAULT_DEDUP_WINDOW_MS = 200;

export function publish(event, payload, options = {}) {
  const dedupWindowMs =
    options?.dedupWindowMs === 0 ? 0 : Number.isFinite(options?.dedupWindowMs) ? options.dedupWindowMs : DEFAULT_DEDUP_WINDOW_MS;
  if (dedupWindowMs > 0) {
    const key = `${String(event)}__${payload == null ? "" : safeKey(payload)}`;
    const now = Date.now();
    const prev = lastPublishedAt.get(key) || 0;
    if (now - prev < dedupWindowMs) return;
    lastPublishedAt.set(key, now);
  }

  const subs = listeners.get(event) || [];
  for (const fn of subs) {
    try {
      fn(payload);
    } catch {
      // Never let a subscriber break the publisher
    }
  }
}

function safeKey(payload) {
  if (typeof payload === "string") return payload.slice(0, 120);
  try {
    return JSON.stringify(payload).slice(0, 180);
  } catch {
    return "unstringifiable";
  }
}

export function subscribe(event, fn) {
  const subs = listeners.get(event) || [];
  listeners.set(event, [...subs, fn]);

  return () => {
    const next = (listeners.get(event) || []).filter((f) => f !== fn);
    if (next.length === 0) listeners.delete(event);
    else listeners.set(event, next);
  };
}

