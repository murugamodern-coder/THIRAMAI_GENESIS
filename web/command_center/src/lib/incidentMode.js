/**
 * Incident / degraded mode — reduce load and disable heavy UI.
 * Set VITE_INCIDENT_MODE=1 at build time (or inject via env at deploy).
 */
export function isIncidentMode() {
  try {
    return (
      typeof import.meta !== "undefined" &&
      String(import.meta.env?.VITE_INCIDENT_MODE || "").toLowerCase() === "1"
    );
  } catch {
    return false;
  }
}
