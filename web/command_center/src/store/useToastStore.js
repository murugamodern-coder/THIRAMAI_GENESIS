import { create } from "zustand";

const DEFAULT_TTL_MS = 4000;
const MAX_VISIBLE = 4;

function uid() {
  return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export const useToastStore = create((set, get) => ({
  toasts: [],
  queue: [],
  timeouts: new Map(),

  show: (input) => {
    const next = {
      id: uid(),
      type: input?.type || "info",
      message: String(input?.message || ""),
      actionLabel: input?.actionLabel,
      onAction: input?.onAction,
      ttlMs: Number.isFinite(input?.ttlMs) ? input.ttlMs : DEFAULT_TTL_MS,
      createdAt: Date.now(),
      leaving: false,
    };

    set((s) => {
      if (s.toasts.length < MAX_VISIBLE) return { ...s, toasts: [...s.toasts, next] };
      return { ...s, queue: [...s.queue, next] };
    });

    if (next.ttlMs > 0) {
      const tid = window.setTimeout(() => {
        get().dismiss(next.id);
      }, next.ttlMs);
      get().timeouts.set(next.id, tid);
    }

    return next.id;
  },

  dismiss: (id) => {
    const s = get();
    const t = s.toasts.find((x) => x.id === id);
    if (!t || t.leaving) return;

    const tid = s.timeouts.get(id);
    if (tid) {
      window.clearTimeout(tid);
      s.timeouts.delete(id);
    }

    set((st) => ({
      ...st,
      toasts: st.toasts.map((x) => (x.id === id ? { ...x, leaving: true } : x)),
    }));

    window.setTimeout(() => {
      get().remove(id);
    }, 220);
  },

  remove: (id) => {
    set((s) => {
      const tid = s.timeouts.get(id);
      if (tid) {
        window.clearTimeout(tid);
        s.timeouts.delete(id);
      }
      const remaining = s.toasts.filter((x) => x.id !== id);
      if (remaining.length === s.toasts.length) return s;

      if (s.queue.length > 0 && remaining.length < MAX_VISIBLE) {
        const [head, ...rest] = s.queue;
        return { ...s, toasts: [...remaining, head], queue: rest };
      }
      return { ...s, toasts: remaining };
    });
  },

  clearAll: () =>
    set((s) => {
      for (const tid of s.timeouts.values()) window.clearTimeout(tid);
      return { toasts: [], queue: [], timeouts: new Map() };
    }),
}));

