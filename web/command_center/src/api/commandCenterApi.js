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

export async function fetchResearchProjects(limit = 80) {
  const { data } = await api.get("/research/projects", { params: { limit } });
  return data;
}

export async function postResearchProject(payload) {
  const { data } = await api.post("/research/projects", payload || {});
  return data;
}

export async function postRunResearchProject(projectId, cycles = 3) {
  const { data } = await api.post(`/research/projects/${encodeURIComponent(projectId)}/run`, { cycles });
  return data;
}

export async function fetchResearchProject(projectId) {
  const { data } = await api.get(`/research/projects/${encodeURIComponent(projectId)}`);
  return data;
}

export async function fetchResearchProjectResults(projectId) {
  const { data } = await api.get(`/research/projects/${encodeURIComponent(projectId)}/results`);
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

export async function deleteInventoryItem(itemId) {
  const { data } = await api.delete(`/inventory/item/${itemId}`);
  return data;
}

export async function fetchAutomationRules() {
  const { data } = await api.get("/automation/rules");
  return data;
}

export async function upsertAutomationRule(payload) {
  const { data } = await api.post("/automation/rules", payload);
  return data;
}

export async function deleteAutomationRule(ruleId) {
  const { data } = await api.delete(`/automation/rules/${encodeURIComponent(ruleId)}`);
  return data;
}

export async function fetchAutomationLogs(limit = 80) {
  const { data } = await api.get("/automation/logs", { params: { limit } });
  return data;
}

export async function postAutomationEvaluate(trigger_type, payload = {}) {
  const { data } = await api.post("/automation/evaluate", { trigger_type, payload });
  return data;
}

export async function fetchOpportunities(params = {}) {
  const { data } = await api.get("/opportunities", { params });
  return data;
}

export async function approveOpportunity(opportunityId) {
  const { data } = await api.post(`/opportunities/${encodeURIComponent(opportunityId)}/approve`);
  return data;
}

export async function executeOpportunity(opportunityId) {
  const { data } = await api.post(`/opportunities/${encodeURIComponent(opportunityId)}/execute`);
  return data;
}

export async function fetchLearningInsights(params = {}) {
  const { data } = await api.get("/learning/insights", { params });
  return data;
}

export async function fetchLearningStrategies(params = {}) {
  const { data } = await api.get("/learning/strategies", { params });
  return data;
}

export async function fetchGovernanceGuardrails() {
  const { data } = await api.get("/governance/guardrails");
  return data;
}

export async function postGovernanceGuardrail(payload) {
  const { data } = await api.post("/governance/guardrails", payload);
  return data;
}

export async function postGovernanceKillSwitch(payload) {
  const { data } = await api.post("/governance/kill-switch", payload);
  return data;
}

export async function fetchGovernanceLogs(limit = 150) {
  const { data } = await api.get("/governance/logs", { params: { limit } });
  return data;
}

export async function startMoneyLoop(payload) {
  const { data } = await api.post("/money-loop/start", payload);
  return data;
}

export async function stopMoneyLoop() {
  const { data } = await api.post("/money-loop/stop");
  return data;
}

export async function fetchMoneyLoopStatus() {
  const { data } = await api.get("/money-loop/status");
  return data;
}

export async function fetchAllocationPreview(params = {}) {
  const { data } = await api.get("/optimizer/allocation-preview", { params });
  return data;
}

export async function fetchSystemOverview() {
  const { data } = await api.get("/system/overview");
  return data;
}

export async function fetchDecisionTrace(executionId) {
  const { data } = await api.get(`/system/decision-trace/${encodeURIComponent(executionId)}`);
  return data;
}

export async function fetchPredictSummary() {
  const { data } = await api.get("/predict/summary");
  return data;
}

export async function fetchPredictRiskAlerts() {
  const { data } = await api.get("/predict/risk-alerts");
  return data;
}

export async function fetchFeedbackAccuracy() {
  const { data } = await api.get("/feedback/accuracy");
  return data;
}

export async function fetchFeedbackDrift() {
  const { data } = await api.get("/feedback/drift");
  return data;
}

export async function fetchAutonomyState() {
  const { data } = await api.get("/autonomy/state");
  return data;
}

export async function postAutonomyState(payload) {
  const { data } = await api.post("/autonomy/state", payload || {});
  return data;
}

export async function fetchAutonomyHeartbeat() {
  const { data } = await api.get("/autonomy/heartbeat");
  return data;
}

export async function postGoalsAutoCreate() {
  const { data } = await api.post("/goals/autocreate");
  return data;
}

export async function fetchGoalsProgress(params = {}) {
  const { data } = await api.get("/goals/progress", { params });
  return data;
}

export async function postGoalCycle(goalId) {
  const { data } = await api.post(`/goals/${encodeURIComponent(goalId)}/cycle`);
  return data;
}

export async function fetchMemoryRecall(params = {}) {
  const { data } = await api.get("/memory/recall", { params });
  return data;
}

export async function fetchPrioritizedGoals() {
  const { data } = await api.get("/goals/prioritized");
  return data;
}

export async function postContinuousThinkingRun() {
  const { data } = await api.post("/autonomy/continuous/run");
  return data;
}

export async function fetchContinuousThinkingStatus() {
  const { data } = await api.get("/autonomy/continuous/status");
  return data;
}

export async function fetchSelfExpansionGaps() {
  const { data } = await api.get("/self-expansion/gaps");
  return data;
}

export async function postSelfExpansionRun() {
  const { data } = await api.post("/self-expansion/run");
  return data;
}

export async function fetchWorldModelContext() {
  const { data } = await api.get("/world-model/context");
  return data;
}

export async function postWorldModelRefresh() {
  const { data } = await api.post("/world-model/refresh");
  return data;
}

export async function postSimulationRun(action_context = {}) {
  const { data } = await api.post("/simulation/run", { action_context });
  return data;
}

export async function postSimulationChoose(action_context = {}) {
  const { data } = await api.post("/simulation/choose", { action_context });
  return data;
}

export async function fetchStrategyGenerate() {
  const { data } = await api.get("/strategy-generator/generate");
  return data;
}

export async function postStrategyTest() {
  const { data } = await api.post("/strategy-generator/test");
  return data;
}

export async function postStrategyPromote() {
  const { data } = await api.post("/strategy-generator/promote");
  return data;
}

export async function postStrategyRun() {
  const { data } = await api.post("/strategy-generator/run");
  return data;
}

export async function fetchMultiOrgOrganizations() {
  const { data } = await api.get("/multi-org/organizations");
  return data;
}

export async function fetchMultiOrgSharedIntelligence() {
  const { data } = await api.get("/multi-org/shared-intelligence");
  return data;
}

export async function fetchMultiOrgExecutionPlan() {
  const { data } = await api.get("/multi-org/execution-plan");
  return data;
}

export async function postRevenueRecord(payload) {
  const { data } = await api.post("/revenue/record", payload || {});
  return data;
}

export async function fetchRevenueSnapshot(params = {}) {
  const { data } = await api.get("/revenue/snapshot", { params });
  return data;
}

export async function postRevenueReinvest(ratio = 0.5) {
  const { data } = await api.post("/revenue/reinvest", null, { params: { ratio } });
  return data;
}

export async function fetchRevenueScaleAllocation(params = {}) {
  const { data } = await api.get("/revenue/scale-allocation", { params });
  return data;
}

export async function postOperationsDailyCycle() {
  const { data } = await api.post("/operations/daily-cycle");
  return data;
}

export async function postOperationsDailyCycleAll() {
  const { data } = await api.post("/operations/daily-cycle/all");
  return data;
}

export async function postSystemBootstrap() {
  const { data } = await api.post("/system/bootstrap");
  return data;
}

export async function fetchSystemRuntimeHealth() {
  const { data } = await api.get("/system/runtime-health");
  return data;
}

export async function postSystemEmergencyStop() {
  const { data } = await api.post("/system/emergency-stop");
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

export async function fetchIntegrations() {
  const { data } = await api.get("/integrations");
  return data;
}

export async function postIntegration(payload) {
  const { data } = await api.post("/integrations", payload);
  return data;
}

export async function postIntegrationTest(payload) {
  const { data } = await api.post("/integrations/test", payload);
  return data;
}

export async function fetchIntegrationLogs(limit = 100) {
  const { data } = await api.get("/integrations/logs", { params: { limit } });
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

export async function postAgentApprove(taskId, body = {}) {
  const missionId = String(body?.mission_id || taskId || "").trim();
  const payload = {
    mission_id: missionId,
    correlation_id: body?.correlation_id ?? null,
    signal: body?.signal || "success",
    execution_mode: body?.execution_mode || null,
  };
  try {
    const { data } = await api.post("/api/agent/approve", payload);
    return data;
  } catch (e) {
    if (e?.response?.status !== 404 && e?.response?.status !== 405) throw e;
    const { data } = await api.post(`/api/agent/approve/${encodeURIComponent(missionId)}`, payload);
    return data;
  }
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

/** Thiramai Code Agent (`/api/agent/*`, `/api/websites/list`). */
export async function postCodeAgentGenerate(payload) {
  const { data } = await api.post("/api/agent/code/generate", payload);
  return data;
}

export async function postCodeAgentSave(payload) {
  const { data } = await api.post("/api/agent/code/save", payload);
  return data;
}

export async function postCodeAgentTest(taskId) {
  const { data } = await api.post("/api/agent/code/test", { task_id: taskId });
  return data;
}

export async function postCodeAgentDeploy(payload) {
  const { data } = await api.post("/api/agent/code/deploy", payload);
  return data;
}

export async function fetchCodeAgentTasks() {
  const { data } = await api.get("/api/agent/code/tasks");
  return data;
}

export async function fetchCodeAgentTask(taskId) {
  const { data } = await api.get(`/api/agent/code/tasks/${encodeURIComponent(taskId)}`);
  return data;
}

export async function postSelfHealAnalyze(errorLog) {
  const { data } = await api.post("/api/agent/self-heal", { error_log: errorLog });
  return data;
}

export async function postSelfHealApply(payload) {
  const { data } = await api.post("/api/agent/self-heal/apply", payload);
  return data;
}

export async function fetchWebsitesList() {
  const { data } = await api.get("/api/websites/list");
  return data;
}
