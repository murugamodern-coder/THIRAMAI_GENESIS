import api, { getToken } from "./client.js";

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
  if (opts.agent_confirm_tool_index != null && Number.isFinite(Number(opts.agent_confirm_tool_index))) {
    body.agent_confirm_tool_index = Number(opts.agent_confirm_tool_index);
  }
  if (opts.agent_reject_tool_index != null && Number.isFinite(Number(opts.agent_reject_tool_index))) {
    body.agent_reject_tool_index = Number(opts.agent_reject_tool_index);
  }
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

/** Part C — Research engine (JWT). */
export async function postResearchMarket(query) {
  const { data } = await api.post("/research/engine/market", { query });
  return data;
}

/** Multi-source deep research (web, news, govt, marketplaces, …). */
export async function postResearchDeep(query, depth = "standard") {
  const { data } = await api.post("/research/engine/deep", { query, depth });
  return data;
}

export async function postResearchSchemes(sector, state = "TN") {
  const { data } = await api.post("/research/engine/schemes", { sector, state });
  return data;
}

export async function postResearchCompetitors(businessType, location = "") {
  const { data } = await api.post("/research/engine/competitors", {
    business_type: businessType,
    location,
  });
  return data;
}

export async function postResearchDpr(body) {
  const { data } = await api.post("/research/engine/dpr", {
    business_type: body.businessType,
    capacity: body.capacity || "",
    location: body.location || "",
  });
  return data;
}

export async function getResearchDprQuery(params) {
  const { data } = await api.get("/research/dpr", {
    params: {
      business_type: params.businessType,
      capacity: params.capacity || "",
      location: params.location || "",
      format: params.format || "json",
    },
  });
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
export async function createOrganization({ email, password, organization_name, plan = "free", invite_code = null }) {
  const body = {
    email,
    password,
    organization_name,
    plan,
  };
  if (invite_code) body.invite_code = String(invite_code).trim();
  const { data } = await api.post("/org/create", body);
  return data;
}

export async function fetchProductBootstrap() {
  const { data } = await api.get("/product/bootstrap");
  return data;
}

export async function fetchProductPlans() {
  const { data } = await api.get("/product/plans");
  return data;
}

export async function postProductDemoSeed() {
  const { data } = await api.post("/product/demo-seed");
  return data;
}

export async function postProductOnboarding(patch) {
  const { data } = await api.post("/product/onboarding", patch);
  return data;
}

export async function fetchWowInsights() {
  const { data } = await api.get("/product/wow-insights");
  return data;
}

export async function createInviteLink() {
  const { data } = await api.post("/product/invite-link");
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

/** Upgrade 5 — receipt vision → preview token (multipart). */
export async function postPersonalExpenseScanPreview(file) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/personal/os/expenses/scan-preview", form);
  return data;
}

export async function postPersonalExpenseScanConfirm(payload, vaultPassphrase) {
  const headers = {};
  if (vaultPassphrase) headers["X-Personal-Vault-Passphrase"] = vaultPassphrase;
  const { data } = await api.post("/personal/os/expenses/scan-confirm", payload, { headers });
  return data;
}

/** Business org — bank CSV/PDF → operational expenses. */
export async function postBusinessBankStatementImport(file) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/business/import-bank-statement", form);
  return data;
}

export async function fetchBusinessGstSuggest(params = {}) {
  const { data } = await api.get("/business/gst-suggest", { params });
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

/** Part D — Stock assistant (JWT). */
export async function fetchStockWatchlist() {
  const { data } = await api.get("/stocks/assistant/watchlist");
  return data;
}

export async function postStockWatchlist(symbol, exchangeSuffix = "NS") {
  const { data } = await api.post("/stocks/assistant/watchlist", {
    symbol,
    exchange_suffix: exchangeSuffix,
  });
  return data;
}

export async function fetchStockQuote(symbol) {
  const { data } = await api.get(`/stocks/assistant/quote/${encodeURIComponent(symbol)}`);
  return data;
}

export async function fetchStockSignal(symbol) {
  const { data } = await api.get(`/stocks/assistant/signal/${encodeURIComponent(symbol)}`);
  return data;
}

export async function fetchStockPortfolio() {
  const { data } = await api.get("/stocks/assistant/portfolio");
  return data;
}

export async function fetchStockMorningBrief() {
  const { data } = await api.get("/stocks/assistant/morning-brief");
  return data;
}

export async function fetchStockRealtimeStatus() {
  const { data } = await api.get("/stocks/assistant/realtime/status");
  return data;
}

export async function fetchStockAlerts() {
  const { data } = await api.get("/stocks/assistant/alerts");
  return data;
}

export async function postStockAlert(payload) {
  const { data } = await api.post("/stocks/assistant/alerts", payload);
  return data;
}

export async function deleteStockAlert(alertId) {
  const { data } = await api.delete(`/stocks/assistant/alerts/${alertId}`);
  return data;
}

/**
 * WebSocket `/ws/stocks/{userId}` — first message must be `{ token }` (JWT).
 * @returns {() => void} disconnect
 */
export function subscribeStockRealtime(userId, handlers = {}) {
  const { onTick, onReady, onError } = handlers;
  const id = Number(userId);
  if (!Number.isFinite(id) || id <= 0) {
    return () => {};
  }
  const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws";
  const host = typeof window !== "undefined" ? window.location.host : "";
  let ws;
  try {
    ws = new WebSocket(`${proto}://${host}/ws/stocks/${id}`);
  } catch (e) {
    onError?.(e);
    return () => {};
  }
  ws.onopen = () => {
    ws.send(JSON.stringify({ token: getToken() || "" }));
  };
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "stock_ws_ready") onReady?.(msg);
      if (msg.type === "stock_tick") onTick?.(msg);
    } catch (e) {
      onError?.(e);
    }
  };
  ws.onerror = (e) => onError?.(e);
  return () => {
    try {
      ws.close();
    } catch {
      // ignore
    }
  };
}

/** Part E — Website builder (JWT). */
export async function postWebsiteBuild(payload) {
  const { data } = await api.post("/website-builder/build", payload);
  return data;
}

export async function postWebsiteDeploy(payload = {}) {
  const { data } = await api.post("/website-builder/deploy", payload);
  return data;
}

export async function fetchWebsitePreviewHtml(organizationId) {
  const { data } = await api.get(`/website-builder/preview/${organizationId}`);
  return data;
}

export async function fetchWebsiteMeta(organizationId) {
  const { data } = await api.get(`/website-builder/meta/${organizationId}`);
  return data;
}

/** Stable browser thread id for agent missions (session-scoped). */
export function ensureAgentCorrelationId(storageKey = "thiramai_agent_correlation_id") {
  if (typeof window === "undefined" || !window.sessionStorage) {
    return `srv-${Date.now()}`;
  }
  try {
    let v = sessionStorage.getItem(storageKey);
    if (!v) {
      v =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `m-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      sessionStorage.setItem(storageKey, v);
    }
    return v;
  } catch {
    return `m-${Date.now()}`;
  }
}

export async function postAgentCommand(payload) {
  const { data } = await api.post("/api/agent/command", payload);
  return data;
}

export async function getAgentPlan(taskId) {
  const { data } = await api.get(`/api/agent/plan/${encodeURIComponent(taskId)}`);
  return data;
}

export async function postAgentApprove(taskId, body) {
  const { data } = await api.post(`/api/agent/approve/${encodeURIComponent(taskId)}`, body ?? {});
  return data;
}

export async function fetchAgentMissions(params = {}) {
  const { data } = await api.get("/api/agent/missions", { params });
  return data;
}

/**
 * Bearer-friendly SSE reader for `/api/agent/plan/{task_id}/events`.
 * Parses `data: {...}` frames until the stream closes.
 */
export async function streamAgentPlan(taskId, onEvent, signal) {
  const token = getToken();
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${typeof window !== "undefined" ? "" : ""}/api/agent/plan/${encodeURIComponent(taskId)}/events`, {
    headers,
    signal,
    credentials: "same-origin",
  });
  if (!res.ok || !res.body) {
    throw new Error(`agent stream HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split(/\n\n/);
    buf = parts.pop() || "";
    for (const block of parts) {
      const lines = block.split(/\n/).filter((l) => l.trim());
      for (const ln of lines) {
        if (ln.startsWith("data:")) {
          const raw = ln.replace(/^data:\s*/, "").trim();
          try {
            onEvent(JSON.parse(raw));
          } catch {
            /* ignore partial json */
          }
        }
      }
    }
  }
}
