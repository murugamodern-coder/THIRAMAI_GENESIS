import { isIncidentMode } from "./incidentMode.js";

/**
 * Env-based feature flags: VITE_FEATURE_<KEY>=1|0|true|false
 * Example: VITE_FEATURE_AI_ASSISTANT=1
 *
 * Keys use UPPER_SNAKE in env; JS API uses camelCase or snake_case:
 *   isFeatureEnabled("AI_ASSISTANT") → VITE_FEATURE_AI_ASSISTANT
 */

const DEFAULT_ON = {
  AI_ASSISTANT: true,
  RECHARTS_DASHBOARD: true,
  COPILOT_CHAT: true,
  QUICK_ACTIONS_FAB: true,
};

/** When incident mode is on, these default to false unless explicitly forced on. */
const INCIDENT_OFF = {
  AI_ASSISTANT: false,
  RECHARTS_DASHBOARD: false,
  COPILOT_CHAT: false,
  QUICK_ACTIONS_FAB: false,
};

function envKey(name) {
  const upper = String(name).replace(/[^A-Za-z0-9_]/g, "_").toUpperCase();
  return `VITE_FEATURE_${upper}`;
}

function parseEnv(v) {
  if (v === undefined || v === null || v === "") return undefined;
  const s = String(v).trim().toLowerCase();
  if (s === "1" || s === "true" || s === "yes" || s === "on") return true;
  if (s === "0" || s === "false" || s === "no" || s === "off") return false;
  return undefined;
}

/**
 * @param {string} name — e.g. "AI_ASSISTANT"
 * @returns {boolean}
 */
export function isFeatureEnabled(name) {
  const key = envKey(name);
  let v;
  try {
    v = typeof import.meta !== "undefined" ? import.meta.env?.[key] : undefined;
  } catch {
    v = undefined;
  }
  const parsed = parseEnv(v);
  if (parsed !== undefined) return parsed;

  if (isIncidentMode()) {
    return INCIDENT_OFF[name] ?? false;
  }
  return DEFAULT_ON[name] ?? true;
}
