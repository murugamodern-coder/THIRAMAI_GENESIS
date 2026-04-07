import { getApiBaseUrl } from "./config";

function formatApiDetail(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((x) =>
        typeof x === "object" && x !== null && "msg" in x
          ? String((x as { msg: string }).msg)
          : JSON.stringify(x)
      )
      .join("; ");
  }
  if (detail != null) return JSON.stringify(detail);
  return `Request failed (${status})`;
}
import type {
  PersonalSummaryResponse,
  PersonalTodayResponse,
  TokenResponse,
} from "./types";

function authHeaders(token: string): HeadersInit {
  return {
    Accept: "application/json",
    Authorization: `Bearer ${token}`,
  };
}

export async function loginWithPassword(
  email: string,
  password: string
): Promise<TokenResponse> {
  const base = getApiBaseUrl();
  const body = new URLSearchParams({
    username: email.trim(),
    password,
  });
  const res = await fetch(`${base}/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
    },
    body: body.toString(),
  });
  const data = (await res.json().catch(() => ({}))) as TokenResponse & {
    detail?: unknown;
  };
  if (!res.ok) {
    const msg = formatApiDetail(data.detail, res.status);
    throw new Error(msg);
  }
  if (!data.access_token) throw new Error("No access token in response");
  return data;
}

export async function fetchPersonalToday(
  token: string
): Promise<PersonalTodayResponse> {
  const base = getApiBaseUrl();
  const res = await fetch(`${base}/personal/today`, {
    headers: authHeaders(token),
  });
  const data = (await res.json().catch(() => ({}))) as PersonalTodayResponse & {
    detail?: string;
  };
  if (!res.ok) {
    throw new Error(formatApiDetail(data.detail, res.status));
  }
  return data;
}

export async function fetchPersonalSummary(
  token: string
): Promise<PersonalSummaryResponse> {
  const base = getApiBaseUrl();
  const res = await fetch(`${base}/personal/summary`, {
    headers: authHeaders(token),
  });
  const data = (await res.json().catch(() => ({}))) as PersonalSummaryResponse & {
    detail?: string;
  };
  if (!res.ok) {
    throw new Error(formatApiDetail(data.detail, res.status));
  }
  return data;
}

export async function postPersonalAction(
  token: string,
  body: Record<string, unknown>
): Promise<{ ok?: boolean; detail?: string; message?: string; executed?: boolean }> {
  const base = getApiBaseUrl();
  const res = await fetch(`${base}/personal/action`, {
    method: "POST",
    headers: {
      ...authHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as {
    ok?: boolean;
    detail?: string;
    message?: string;
    executed?: boolean;
  };
  if (!res.ok) {
    throw new Error(formatApiDetail(data.detail, res.status));
  }
  return data;
}
