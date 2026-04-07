/**
 * WebSocket-ready scaffold (Phase 2).
 *
 * This intentionally does not implement backend-specific message formats yet.
 */
export function createLiveConnection() {
  /** @type {WebSocket|null} */
  let ws = null;
  const handlers = new Map(); // event -> Set<fn>

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

  return {
    connect(url) {
      if (ws) return;
      ws = new WebSocket(url);
      ws.addEventListener("open", () => emit("open"));
      ws.addEventListener("close", () => emit("close"));
      ws.addEventListener("error", (e) => emit("error", e));
      ws.addEventListener("message", (msg) => emit("message", msg));
    },
    disconnect() {
      if (!ws) return;
      try {
        ws.close();
      } finally {
        ws = null;
      }
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

