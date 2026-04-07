import { createInventoryItem, resolveDecision } from "../api/commandCenterApi.js";
import { publish } from "./eventBus.js";
import { logAudit } from "./auditLogger.js";
import { evaluateRules } from "./rulesEngine.js";
import { getCurrentRole } from "../store/useCommandStore.js";

function asNumber(x) {
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}

function required(payload, field) {
  if (!payload || payload[field] == null || payload[field] === "") {
    throw new Error(`Missing required payload field: ${field}`);
  }
}

function isDestructive(action) {
  const t = String(action?.type || "");
  return t === "approve_invoice" || t === "resolve_mission" || t === "inventory_reorder";
}

export function getActionConfirmation(action) {
  if (!isDestructive(action)) return null;
  switch (String(action?.type || "")) {
    case "inventory_reorder":
      return "Create a reorder / inventory entry now?";
    case "approve_invoice":
      return "Approve this invoice now?";
    case "resolve_mission":
      return "Resolve this mission now?";
    default:
      return "Run this action now?";
  }
}

/**
 * Central action execution handler for AI suggested actions.
 *
 * Each action:
 *  - type: string
 *  - payload: object
 */
export async function runAIAction(action) {
  if (!action || typeof action !== "object") throw new Error("Unknown action");
  const type = String(action.type || "");
  const payload = action.payload || {};

  const rule = evaluateRules(action, { role: getCurrentRole() });
  if (rule?.allowed === false) {
    logAudit({
      actionType: `ai_action:${type}`,
      entity: type,
      entityId: payload?.id ?? payload?.name ?? null,
      source: "AI",
      result: "FAIL",
      details: { reason: rule.reason, code: rule.code },
    });
    throw new Error(rule.reason || "Blocked by business rules");
  }

  switch (type) {
    case "inventory_reorder": {
      // No dedicated reorder endpoint exists yet; implement as a create-inventory-item intent.
      // Supported payloads:
      //  - { name, quantity, unit? }
      //  - { sku_name, quantity, location?, unit_price?, reorder_point? }
      const name = String(payload.name || payload.sku_name || payload.itemId || payload.sku || "").trim();
      const qty = asNumber(payload.quantity);
      if (!name) throw new Error("Missing item name");
      if (qty == null) throw new Error("Missing quantity");

      // Prefer passing through any additional fields if provided.
      const outPayload =
        payload.sku_name || payload.location || payload.unit_price != null || payload.reorder_point != null
          ? {
              sku_name: name,
              location: String(payload.location || "reorder").trim(),
              quantity: qty,
              unit_price: payload.unit_price != null ? asNumber(payload.unit_price) : null,
              reorder_point: payload.reorder_point != null ? asNumber(payload.reorder_point) : null,
            }
          : {
              name,
              quantity: qty,
              unit: payload.unit ? String(payload.unit) : undefined,
            };

      const out = await createInventoryItem(outPayload);
      logAudit({
        actionType: "inventory_reorder",
        entity: "inventory",
        entityId: name,
        source: "AI",
        result: "SUCCESS",
        details: { quantity: qty },
      });
      publish("inventory:updated", { type: "inventory_reorder" });
      publish("dashboard:refresh", { source: "inventory:updated" });
      return out;
    }

    case "resolve_mission": {
      required(payload, "id");
      const id = asNumber(payload.id);
      const status = String(payload.status || "approved");
      if (!id) throw new Error("Missing mission id");
      const out = await resolveDecision(id, status);
      logAudit({
        actionType: `mission_${status}`,
        entity: "mission",
        entityId: id,
        source: "AI",
        result: "SUCCESS",
      });
      publish("mission:updated", { id, status });
      publish("dashboard:refresh", { source: "mission:updated" });
      return out;
    }

    case "approve_invoice": {
      // Backend API for invoice approval isn't exposed in current commandCenterApi.
      required(payload, "id");
      throw new Error("approve_invoice is not yet wired (missing billing approval endpoint).");
    }

    case "navigate": {
      required(payload, "to");
      return { ok: true, navigate_to: payload.to };
    }

    default:
      throw new Error("Unknown action");
  }
}
