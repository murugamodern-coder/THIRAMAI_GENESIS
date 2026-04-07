import api from "./client.js";

export async function fetchCommandCenterSnapshot(params = {}) {
  const { data } = await api.get("/dashboard/command-center", { params });
  return data;
}

export async function fetchPendingDecisions(limit = 50) {
  const { data } = await api.get("/chat/decisions/pending", { params: { limit } });
  return data;
}

export async function resolveDecision(decisionId, status) {
  const { data } = await api.post(`/chat/decision/${decisionId}/resolve`, { status });
  return data;
}

export async function postChatQuery(message) {
  const { data } = await api.post("/chat/query", { message });
  return data;
}

export async function fetchMyOrganizations() {
  const { data } = await api.get("/me/organizations");
  return data;
}

export async function switchOrganization(orgId) {
  const { data } = await api.post(`/me/switch-organization/${orgId}`);
  return data;
}

export async function fetchAuthMe() {
  const { data } = await api.get("/auth/me");
  return data;
}

export async function fetchAnalyticsSummary(days = 30) {
  const { data } = await api.get("/analytics/summary", { params: { days } });
  return data;
}

export async function postUsageEvent(action, metadata) {
  const { data } = await api.post("/analytics/usage-event", { action, metadata: metadata ?? null });
  return data;
}

export async function loginWithPassword(username, password) {
  const body = new URLSearchParams();
  body.set("username", username);
  body.set("password", password);
  const { data } = await api.post("/auth/login", body, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data;
}

/** SaaS onboarding — same as POST /auth/register with explicit plan. */
export async function createOrganization({ email, password, organization_name, plan = "free" }) {
  const { data } = await api.post("/org/create", {
    email,
    password,
    organization_name,
    plan,
  });
  return data;
}

export async function fetchInventoryList() {
  const { data } = await api.get("/inventory");
  return data;
}

export async function fetchInventoryAlerts(threshold) {
  const { data } = await api.get("/inventory/alerts", {
    params: threshold != null ? { threshold } : {},
  });
  return data;
}

export async function createInventoryItem(payload) {
  const { data } = await api.post("/inventory/item", payload);
  return data;
}

export async function updateInventoryItem(itemId, payload) {
  const { data } = await api.put(`/inventory/item/${itemId}`, payload);
  return data;
}

export async function fetchInvoices(limit = 200) {
  const { data } = await api.get("/billing/invoices", { params: { limit } });
  return data;
}

export async function recordPayment(payload) {
  const { data } = await api.post("/billing/payment", payload);
  return data;
}

export async function createStructuredInvoice(payload) {
  const { data } = await api.post("/billing/invoice", payload);
  return data;
}

export async function fetchProductionSummary(startDate, endDate) {
  const { data } = await api.get("/production/summary", {
    params: {
      ...(startDate ? { start_date: startDate } : {}),
      ...(endDate ? { end_date: endDate } : {}),
    },
  });
  return data;
}

export async function fetchProductionMachines() {
  const { data } = await api.get("/production/machines");
  return data;
}

export async function createMaintenanceLog(payload) {
  const { data } = await api.post("/production/maintenance", payload);
  return data;
}
