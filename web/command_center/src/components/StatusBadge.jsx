import { memo } from "react";

/** @param {{ level: 'ok' | 'warn' | 'crit', label?: string }} props */
function StatusBadge({ level, label }) {
  const cls =
    level === "crit"
      ? "cc-badge cc-badge--crit"
      : level === "warn"
        ? "cc-badge cc-badge--warn"
        : "cc-badge cc-badge--ok";
  const text =
    label != null && String(label).trim() !== ""
      ? label
      : level === "crit"
        ? "Critical"
        : level === "warn"
          ? "Warning"
          : "Healthy";
  return <span className={cls}>{text}</span>;
}

export default memo(StatusBadge);

export function levelFromScore(value) {
  if (value == null || Number.isNaN(Number(value))) return "ok";
  const n = Number(value);
  if (n < 40) return "crit";
  if (n < 70) return "warn";
  return "ok";
}

export function levelFromBusinessOk(ok) {
  if (ok === false) return "crit";
  return "ok";
}
