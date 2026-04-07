import { PERMISSIONS, can } from "./rbac.js";
import { getCurrentRole } from "../store/useCommandStore.js";
import { getLiveSnapshot } from "./runtimeContext.js";

export function evaluateRules(action, context = {}) {
  const role = context.role || getCurrentRole();
  const snapshot = context.snapshot || getLiveSnapshot();

  // System health guard: if emergency queue exists, block non-admin execution.
  const emergency = snapshot?.priority_counts?.emergency ?? 0;
  if (emergency > 0 && !can(role, PERMISSIONS.OVERRIDE_AI)) {
    return { allowed: false, reason: "System health is critical. Actions are temporarily blocked.", code: "HEALTH_BLOCK" };
  }

  // Example: very large inventory reorder requires admin approval.
  if (action?.type === "inventory_reorder") {
    const qty = Number(action?.payload?.quantity);
    if (Number.isFinite(qty) && qty > 1000 && !can(role, PERMISSIONS.OVERRIDE_AI)) {
      return { allowed: false, reason: "Large reorder requires ADMIN approval.", code: "ADMIN_REQUIRED" };
    }
  }

  // Default allow.
  return { allowed: true };
}

