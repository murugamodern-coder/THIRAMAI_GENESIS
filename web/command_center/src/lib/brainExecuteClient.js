import api from "../api/client.js";

/**
 * POST /brain/execute — single execution pipeline (requires JWT + /auth/me for ids).
 */
export async function postBrainCommand(command) {
  const cmd = String(command || "").trim();
  if (!cmd) throw new Error("Command is empty");

  const { data: me } = await api.get("/auth/me");
  const userId = Number(me?.id);
  const organizationId = Number(me?.organization?.id);
  if (!Number.isFinite(userId) || userId <= 0) {
    throw new Error("Not signed in");
  }
  if (!Number.isFinite(organizationId) || organizationId <= 0) {
    throw new Error("No active organization");
  }

  const { data } = await api.post("/brain/execute", {
    command: cmd,
    user_id: userId,
    organization_id: organizationId,
  });
  return data;
}

/** One-line summary for chat bubbles / TTS. */
export function summarizeBrainReply(brain) {
  if (!brain || typeof brain !== "object") return "Done.";
  const st = String(brain.status || "");
  const intent = String(brain.intent || "");
  const r = brain.result;
  const stopped = r && typeof r === "object" ? r.stopped : null;
  const reason = stopped && typeof stopped === "object" ? String(stopped.reason || "") : "";
  if (reason === "medium_risk_batch_confirm_required") {
    return "Plan ready — confirm medium-risk steps in Actions to continue.";
  }
  if (reason === "high_risk_requires_explicit_ok") {
    return "High-risk step needs explicit confirmation before running.";
  }
  if (r && typeof r === "object" && r.blocked) {
    return String(r.reason || "Blocked by safety or governance.");
  }
  if (r && typeof r === "object" && r.error) {
    return `Stopped: ${r.error}`;
  }
  if (st === "success") return `Completed (${intent || "general"}).`;
  if (st === "partial") return `Partially completed (${intent || "general"}).`;
  if (st === "failed") return `Did not complete (${intent || "general"}).`;
  return `Status: ${st || "unknown"}`;
}
