import axios from "axios";

import { reportAxiosError, reportAxiosSuccess } from "../lib/telemetry.js";

export const TOKEN_KEY = "thiramai_jwt";

export function getToken() {
  return typeof localStorage !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/** Same-origin API (FastAPI). Vite dev proxy forwards to backend. */
const api = axios.create({
  baseURL: "",
  headers: { "Content-Type": "application/json" },
  timeout: 120_000,
});

api.interceptors.request.use((config) => {
  const c = config;
  if (typeof performance !== "undefined") {
    c.metadata = { ...(c.metadata || {}), start: performance.now() };
  }
  const t = getToken();
  if (t) c.headers.Authorization = `Bearer ${t}`;
  return c;
});

api.interceptors.response.use(
  (res) => {
    try {
      reportAxiosSuccess(res);
    } catch {
      /* telemetry must not break responses */
    }
    return res;
  },
  (err) => {
    try {
      reportAxiosError(err);
    } catch {
      /* ignore */
    }
    // Hypothesis H4: requests reach backend but are rejected with 401 -> UI shows "Network Error".
    // For HashRouter, redirecting via window.location.hash is reliable and avoids hook usage here.
    if (Number(err?.response?.status) === 401) {
      try {
        setToken(null);
      } catch {
        // ignore
      }
      try {
        if (typeof window !== "undefined") window.location.hash = "#/login";
      } catch {
        // ignore
      }
    }
    return Promise.reject(err);
  },
);

export default api;
