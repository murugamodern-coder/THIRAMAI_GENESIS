/** FastAPI default port 8000; optional Node Jarvis bridge (OpenAI) via REACT_APP_JARVIS_URL. */

const BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';
export const JARVIS_NODE_URL = process.env.REACT_APP_JARVIS_URL || 'http://localhost:4000';

/** Attach after login: `localStorage.setItem('thiramai_access_token', access)` from `/auth/login`. */
export function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (typeof localStorage !== 'undefined') {
    const token = localStorage.getItem('thiramai_access_token');
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }
  return headers;
}

async function request(method, path, body, timeoutMs = 8000) {
  const ms = Number(timeoutMs);
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'omit',
    headers: body ? { 'Content-Type': 'application/json', ...authHeaders() } : authHeaders(),
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(Number.isFinite(ms) ? ms : 8000),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    throw Object.assign(new Error(err.detail || err.error || err.message || 'Request failed'), {
      status: res.status, code: err.code,
    });
  }
  return res.json();
}

export const api = {
  get: (path, timeoutMs) => request('GET', path, undefined, timeoutMs),
  post: (path, body, timeoutMs) => request('POST', path, body, timeoutMs),
  patch: (path, body, timeoutMs) => request('PATCH', path, body, timeoutMs),
  delete: (path, timeoutMs) => request('DELETE', path, undefined, timeoutMs),
};

export const osApi = {
  getStatus: (osKey) => api.get(`/api/os/${osKey}/status`),
  getSettings: (osKey) => api.get(`/api/os/${osKey}/settings`),
  saveSettings: (osKey, data) => api.patch(`/api/os/${osKey}/settings`, data),
};

/** Session-scoped thread id so missions group in ``agent_tasks`` + dashboards. */
export function ensureAgentCorrelationId(storageKey = 'thiramai_agent_correlation_id') {
  if (typeof window === 'undefined' || !window.sessionStorage) {
    return `m-${Date.now()}`;
  }
  try {
    let v = sessionStorage.getItem(storageKey);
    if (!v) {
      v =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `m-${Date.now()}`;
      sessionStorage.setItem(storageKey, v);
    }
    return v;
  } catch {
    return `m-${Date.now()}`;
  }
}

/** @deprecated Prefer ``agentApi.command`` (FastAPI agentic workflow). Kept for local Node experiments. */
async function jarvisPost(body) {
  const res = await fetch(`${JARVIS_NODE_URL}/api/jarvis/ask`, {
    method: 'POST',
    credentials: 'omit',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw Object.assign(new Error(data.error || data.detail || `HTTP ${res.status}`), { status: res.status });
  }
  return data;
}

export const agentApi = {
  /** Plan → approve loop (FastAPI ``services.orchestrator``). */
  command: (command, osKey = 'stock', executionMode = 'paper', correlationId = null, timeoutMs = 120000) =>
    api.post(
      '/api/agent/command',
      {
        command,
        os_key: osKey,
        execution_mode: executionMode,
        correlation_id: correlationId || ensureAgentCorrelationId(),
      },
      timeoutMs,
    ),
  approve: (taskId, signal = 'success', executionMode = 'paper') =>
    api.post(
      `/api/agent/approve/${encodeURIComponent(taskId)}`,
      { signal, execution_mode: executionMode === 'live' ? 'live' : 'paper' },
      120000
    ),
  getPlan: (taskId) => api.get(`/api/agent/plan/${encodeURIComponent(taskId)}`, 30000),
  listMissions: (params = {}) => {
    const q = new URLSearchParams();
    if (params.limit != null) q.set('limit', String(params.limit));
    if (params.os_key) q.set('os_key', String(params.os_key));
    const s = q.toString();
    return api.get(`/api/agent/missions${s ? `?${s}` : ''}`, 30000);
  },
};

/**
 * Jarvis chat on thiramai.co.in — routes to POST /api/agent/command (plan → approve → execute).
 * Returns the same payload as ``agentApi.command`` (not a free-text LLM reply).
 */
export const jarvisApi = {
  ask: (question, _context, osKey = 'stock') =>
    agentApi.command(
      question,
      osKey === 'research' ? 'research' : 'stock',
      'paper',
      ensureAgentCorrelationId(),
    ),
  /** Opt into legacy Node bridge explicitly. */
  askLegacyNode: (question, context, osKey) => jarvisPost({ question, context, osKey }),
};

export const personalApi = {
  getTasks: () => api.get('/api/os/personal/tasks'),
  getSchedule: () => api.get('/api/os/personal/schedule'),
};

export const stockApi = {
  getSignals: () => api.get('/api/os/stock/signals'),
};

export const researchApi = {
  createMission: (data) => api.post('/api/os/research/mission', data),
  getMissionStatus: (id) => api.get(`/api/os/research/mission/${id}/status`),
};

export const autonomyThiramaiApi = {
  submitGoal: (goal, maxSeconds) =>
    api.post('/ai/goal', { goal, max_seconds: maxSeconds ?? null }),
  getStatus: (jobId) => api.get(`/ai/status?job_id=${encodeURIComponent(jobId)}`),
  getHistory: (limit = 25) => api.get(`/ai/history?limit=${encodeURIComponent(limit)}`),
  getLogs: (jobId, tail = 200) =>
    api.get(`/ai/logs?job_id=${encodeURIComponent(jobId)}&tail=${encodeURIComponent(tail)}`),
  replayJob: (jobId) => api.post('/ai/replay', { job_id: jobId }),
  getQueue: () => api.get('/ai/queue'),
  getWorkers: () => api.get('/ai/workers'),
  listApprovals: () => api.get('/ai/approvals'),
  approve: (approvalId) => api.post('/ai/approve', { approval_id: approvalId }),
  reject: (approvalId, reason) => api.post('/ai/reject', { approval_id: approvalId, reason: reason || '' }),
  internalState: () => api.get('/ai/internal/state'),
  internalMetrics: () => api.get('/ai/internal/metrics'),
  internalLastErrors: (limit = 25) => api.get(`/ai/internal/last-errors?limit=${encodeURIComponent(limit)}`),
};
