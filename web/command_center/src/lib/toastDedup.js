import { showToast } from "./toast.js";

const DEDUPE_WINDOW_MS = 2000;
const lastShown = new Map();

function keyFor(input) {
  const type = input?.type || "info";
  const message = String(input?.message || "");
  return `${type}__${message}`;
}

export function showToastDedup(input) {
  const k = keyFor(input);
  const now = Date.now();
  const prev = lastShown.get(k) || 0;
  if (now - prev < DEDUPE_WINDOW_MS) return null;
  lastShown.set(k, now);
  return showToast(input);
}

