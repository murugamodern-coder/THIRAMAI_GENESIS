/**
 * Safe collection for `.map` / iteration — avoids undefined/null `.map` crashes.
 * Prefer: safeArray(x).map(...) over x.map(...)
 */
export function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

/**
 * Optional property read with fallback (safe access pattern).
 */
export function safeGet(obj, key, defaultValue = undefined) {
  if (obj == null || typeof obj !== "object") return defaultValue;
  const v = obj[key];
  return v === undefined || v === null ? defaultValue : v;
}

/**
 * String coalesce for display text.
 */
export function safeStr(value, fallback = "") {
  if (value === undefined || value === null) return fallback;
  return String(value);
}
