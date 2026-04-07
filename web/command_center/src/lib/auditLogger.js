import { postUsageEvent } from "../api/commandCenterApi.js";
import { useCommandStore } from "../store/useCommandStore.js";

const KEY = "cc_audit_log_v1";
const MAX_ROWS = 500;

function nowIso() {
  return new Date().toISOString();
}

function safeRead() {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function safeWrite(rows) {
  try {
    localStorage.setItem(KEY, JSON.stringify(rows.slice(0, MAX_ROWS)));
  } catch {
    /* ignore quota errors */
  }
}

export function logAudit({
  userId,
  actionType,
  entity,
  entityId,
  source = "USER",
  result = "SUCCESS",
  details,
}) {
  const me = useCommandStore.getState().me;
  const row = {
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    userId: userId ?? me?.id ?? null,
    actionType: String(actionType || "unknown"),
    entity: String(entity || "unknown"),
    entityId: entityId ?? null,
    timestamp: nowIso(),
    source: source === "AI" ? "AI" : "USER",
    result: result === "FAIL" ? "FAIL" : "SUCCESS",
    details: details ?? null,
  };

  const prev = safeRead();
  safeWrite([row, ...prev]);

  // Optional server mirror: best-effort (usage_logs).
  try {
    postUsageEvent("audit_log", {
      ...row,
      email: me?.email || null,
      organization_id: me?.organization_id || null,
    }).catch(() => null);
  } catch {
    /* ignore */
  }

  return row;
}

export function queryAudit({ q, userId, actionType, fromIso, toIso, limit = 100 } = {}) {
  const rows = safeRead();
  const qn = String(q || "").trim().toLowerCase();
  const from = fromIso ? Date.parse(fromIso) : null;
  const to = toIso ? Date.parse(toIso) : null;

  const out = rows.filter((r) => {
    if (userId != null && String(r.userId) !== String(userId)) return false;
    if (actionType && String(r.actionType) !== String(actionType)) return false;
    if (from != null || to != null) {
      const t = Date.parse(r.timestamp);
      if (Number.isFinite(from) && t < from) return false;
      if (Number.isFinite(to) && t > to) return false;
    }
    if (qn) {
      const blob = `${r.actionType} ${r.entity} ${r.entityId ?? ""} ${r.result} ${r.source}`.toLowerCase();
      if (!blob.includes(qn)) return false;
    }
    return true;
  });

  return out.slice(0, Math.max(1, Math.min(500, limit)));
}

