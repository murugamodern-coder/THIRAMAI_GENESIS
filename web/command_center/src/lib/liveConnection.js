/**
 * WebSocket client with reconnect + exponential backoff (dashboard / stocks).
 * Server may emit ``{ type: "pong" }`` in response to ``{ type: "ping" }``.
 */

const DEFAULT_MAX_RETRIES = 8;
const BASE_DELAY_MS = 1200;
const MAX_DELAY_MS = 30_000;

export function createLiveConnection() {
  /** @type {WebSocket|null} */
  let ws = null;
  /** @type {ReturnType<typeof setInterval>|null} */
  let pingTimer = null;
  let reconnectAttempts = 0;
  let closedByUser = false;
  /** @type {string|null} */
  let lastUrl = null;
  const handlers = new Map();

  function emit(event, payload) {
    const set = handlers.get(event);
    if (!set) return;
    for (const fn of set) {
      try {
        fn(payload);
      } catch {
        /* ignore handler failure */
      }
    }
  }

  function clearPing() {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  function scheduleReconnect() {
    if (closedByUser || !lastUrl) return;
    if (reconnectAttempts >= DEFAULT_MAX_RETRIES) {
      emit("error", new Error("max reconnects"));
      return;
    }
    const exp = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** reconnectAttempts);
    const jitter = Math.floor(Math.random() * 400);
    reconnectAttempts += 1;
    setTimeout(() => {
      if (!closedByUser && lastUrl) internalConnect(lastUrl);
    }, exp + jitter);
  }

  function internalConnect(url) {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    ws = new WebSocket(url);
    ws.addEventListener("open", () => {
      reconnectAttempts = 0;
      emit("open");
      clearPing();
      pingTimer = setInterval(() => {
        try {
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        } catch {
          /* ignore */
        }
      }, 25_000);
    });
    ws.addEventListener("close", () => {
      clearPing();
      emit("close");
      ws = null;
      if (!closedByUser) scheduleReconnect();
    });
    ws.addEventListener("error", (e) => emit("error", e));
    ws.addEventListener("message", (msg) => emit("message", msg));
  }

  return {
    connect(url) {
      closedByUser = false;
      lastUrl = url;
      internalConnect(url);
    },
    disconnect() {
      closedByUser = true;
      lastUrl = null;
      clearPing();
      if (!ws) return;
      try {
        ws.close();
      } finally {
        ws = null;
      }
    },
    send(obj) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(typeof obj === "string" ? obj : JSON.stringify(obj));
      return true;
    },
    subscribe(event, handler) {
      if (!handlers.has(event)) handlers.set(event, new Set());
      handlers.get(event).add(handler);
      return () => handlers.get(event)?.delete(handler);
    },
    get isConnected() {
      return ws?.readyState === WebSocket.OPEN;
    },
  };
}
