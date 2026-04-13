import api from "./client.js";

/** Open GST invoice HTML in a new tab (uses JWT from axios). */
export async function openStructuredInvoicePrint(invoiceId, supplyMode = "intra") {
  const { data } = await api.get(`/billing/invoice/${invoiceId}/html`, {
    params: { supply_mode: supplyMode },
    responseType: "text",
    transformResponse: [(d) => d],
  });
  const w = window.open("", "_blank");
  if (!w) return false;
  w.document.write(data);
  w.document.close();
  return true;
}

/** Open non-GST cash bill HTML in a new tab. */
export async function openCashBillPrint(billId) {
  const { data } = await api.get(`/billing/bill/${billId}/html`, {
    responseType: "text",
    transformResponse: [(d) => d],
  });
  const w = window.open("", "_blank");
  if (!w) return false;
  w.document.write(data);
  w.document.close();
  return true;
}

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

export async function postChatQuery(message, opts = {}) {
  const body = {
    message: message ?? "",
    agent_mode: !!opts.agent_mode,
    agent_confirm: !!opts.agent_confirm,
    agent_pending_id: opts.agent_pending_id ?? null,
    agent_undo: !!opts.agent_undo,
  };
  if (opts.jarvis_context_org_id != null && opts.jarvis_context_org_id !== "") {
    const n = Number(opts.jarvis_context_org_id);
    if (Number.isFinite(n) && n > 0) body.jarvis_context_org_id = n;
  }
  const { data } = await api.post("/chat/query", body);
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

export async function fetchProductionAssets() {
  const { data } = await api.get("/production/assets");
  return data;
}

export async function createMaintenanceLog(payload) {
  const { data } = await api.post("/production/maintenance", payload);
  return data;
}

/** Personal Command Center (`/personal/os/*`) — optional vault header for encrypted fields. */
function _vaultHeaders(vaultPassphrase) {
  const h = {};
  if (vaultPassphrase && String(vaultPassphrase).trim()) {
    h["X-Personal-Vault-Passphrase"] = String(vaultPassphrase).trim();
  }
  return h;
}

export async function fetchPersonalMorningBrief(vaultPassphrase) {
  const { data } = await api.get("/personal/os/morning-brief", { headers: _vaultHeaders(vaultPassphrase) });
  return data;
}

/** Unified hero Today payload (morning brief + business + max 3 alerts). */
export async function fetchPersonalTodayBrief(vaultPassphrase) {
  const { data } = await api.get("/personal/os/today-brief", { headers: _vaultHeaders(vaultPassphrase) });
  return data;
}

export async function fetchPersonalWeeklyReview() {
  const { data } = await api.get("/personal/os/weekly-review");
  return data;
}

export async function fetchPersonalExpenses(limit = 100) {
  const { data } = await api.get("/personal/os/expenses", { params: { limit } });
  return data;
}

export async function createPersonalExpense(payload, vaultPassphrase) {
  const { data } = await api.post("/personal/os/expenses", payload, { headers: _vaultHeaders(vaultPassphrase) });
  return data;
}

export async function fetchPersonalLoans() {
  const { data } = await api.get("/personal/os/loans");
  return data;
}

export async function createPersonalLoan(payload, vaultPassphrase) {
  const { data } = await api.post("/personal/os/loans", payload, { headers: _vaultHeaders(vaultPassphrase) });
  return data;
}

export async function fetchPersonalVitals(limit = 60) {
  const { data } = await api.get("/personal/os/vitals", { params: { limit } });
  return data;
}

export async function createPersonalVital(payload, vaultPassphrase) {
  const { data } = await api.post("/personal/os/vitals", payload, { headers: _vaultHeaders(vaultPassphrase) });
  return data;
}

export async function fetchPersonalBudgets() {
  const { data } = await api.get("/personal/os/budgets");
  return data;
}

export async function createPersonalBudget(payload) {
  const { data } = await api.post("/personal/os/budgets", payload);
  return data;
}

export async function fetchPersonalMedicines() {
  const { data } = await api.get("/personal/os/medicines");
  return data;
}

export async function createPersonalMedicine(payload, vaultPassphrase) {
  const { data } = await api.post("/personal/os/medicines", payload, { headers: _vaultHeaders(vaultPassphrase) });
  return data;
}

/** Life OS (`/life/*`) — vault header used for encrypted health reflection only. */
export async function fetchLifeDashboard() {
  const { data } = await api.get("/life/dashboard");
  return data;
}

export async function postLifeHabit(payload) {
  const { data } = await api.post("/life/habit", payload);
  return data;
}

export async function postLifeHabitCheckIn(payload) {
  const { data } = await api.post("/life/habit/check-in", payload);
  return data;
}

export async function postLifeHealth(payload, vaultPassphrase) {
  const { data } = await api.post("/life/health", payload, { headers: _vaultHeaders(vaultPassphrase) });
  return data;
}

export async function postLifeMission(payload) {
  const { data } = await api.post("/life/mission", payload);
  return data;
}

/** Personal OS — meetings / appointments */
export async function fetchPersonalMeetingsToday() {
  const { data } = await api.get("/personal/os/meetings/today");
  return data;
}

export async function fetchPersonalMeetingsUpcoming() {
  const { data } = await api.get("/personal/os/meetings/upcoming");
  return data;
}

export async function createPersonalMeeting(payload) {
  const { data } = await api.post("/personal/os/meetings", payload);
  return data;
}

export async function completePersonalMeeting(meetingId, payload) {
  const { data } = await api.post(`/personal/os/meetings/${meetingId}/complete`, payload ?? {});
  return data;
}

/** Google Calendar integration */
export async function postGoogleCalendarConnect() {
  const { data } = await api.post("/integrations/google/connect");
  return data;
}

export async function fetchGoogleCalendarStatus() {
  const { data } = await api.get("/integrations/google/status");
  return data;
}

export async function postGoogleCalendarSync() {
  const { data } = await api.post("/integrations/google/sync");
  return data;
}

export async function postGoogleCalendarDisconnect() {
  const { data } = await api.post("/integrations/google/disconnect");
  return data;
}

/** Tenant Business OS (`/business/*`) — active org from JWT. */
export async function fetchBusinessSnapshot() {
  const { data } = await api.get("/business/snapshot");
  return data;
}

export async function fetchBusinessPlDaily() {
  const { data } = await api.get("/business/pl-daily");
  return data;
}

export async function fetchBusinessExpenseList(params = {}) {
  const { data } = await api.get("/business/expenses/list", { params });
  return data;
}

export async function postBusinessExpense(payload) {
  const { data } = await api.post("/business/expenses", payload);
  return data;
}

export async function fetchSubsidyCases(limit = 200) {
  const { data } = await api.get("/business/subsidy", { params: { limit } });
  return data;
}

export async function postSubsidyCase(payload) {
  const { data } = await api.post("/business/subsidy", payload);
  return data;
}

export async function patchSubsidyCase(caseId, payload) {
  const { data } = await api.patch(`/business/subsidy/${caseId}`, payload);
  return data;
}

export async function fetchBusinessTasks(limit = 200) {
  const { data } = await api.get("/business/tasks", { params: { limit } });
  return data;
}

export async function postBusinessTask(payload) {
  const { data } = await api.post("/business/tasks", payload);
  return data;
}

export async function patchBusinessTask(taskId, payload) {
  const { data } = await api.patch(`/business/tasks/${taskId}`, payload);
  return data;
}

export async function fetchBillingBills(limit = 100) {
  const { data } = await api.get("/billing/bills", { params: { limit } });
  return data;
}

export async function postSimpleCashBill(payload) {
  const { data } = await api.post("/billing/simple-bill", payload);
  return data;
}

export async function postInventoryStockMovement(payload) {
  const { data } = await api.post("/inventory/movement", payload);
  return data;
}

export async function fetchInventorySuppliers() {
  const { data } = await api.get("/inventory/suppliers");
  return data;
}

export async function createInventorySupplier(payload) {
  const { data } = await api.post("/inventory/supplier", payload);
  return data;
}
