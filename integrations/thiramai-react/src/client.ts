/**
 * Low-level HTTP helpers — Bearer auth, JSON, typed errors.
 */

import type { ThiramaiClientError } from "./types";

export type GetToken = () => string | null | Promise<string | null>;

export type ThiramaiClientConfig = {
  /** e.g. https://api.example.com — no trailing slash */
  baseUrl: string;
  getAccessToken: GetToken;
  /** Optional fetch (Next.js server fetch with cache tags, etc.) */
  fetchImpl?: typeof fetch;
};

function joinUrl(baseUrl: string, path: string): string {
  const b = baseUrl.replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${b}${p}`;
}

export class ThiramaiHttpError extends Error {
  readonly status: number;
  readonly body?: unknown;

  constructor(msg: string, status: number, body?: unknown) {
    super(msg);
    this.name = "ThiramaiHttpError";
    this.status = status;
    this.body = body;
  }

  toJSON(): ThiramaiClientError {
    return { status: this.status, message: this.message, body: this.body };
  }
}

export async function resolveToken(getAccessToken: GetToken): Promise<string | null> {
  const t = getAccessToken();
  return t instanceof Promise ? await t : t;
}

export async function thiramaiFetchJson<T>(
  cfg: ThiramaiClientConfig,
  path: string,
  init: RequestInit & { searchParams?: Record<string, string | number | boolean | undefined> } = {}
): Promise<T> {
  const { searchParams, headers: extraHeaders, ...rest } = init;
  let url = joinUrl(cfg.baseUrl, path);
  if (searchParams) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(searchParams)) {
      if (v === undefined) continue;
      q.set(k, String(v));
    }
    const qs = q.toString();
    if (qs) url += `?${qs}`;
  }

  const token = await resolveToken(cfg.getAccessToken);
  const headers = new Headers(extraHeaders);
  headers.set("Accept", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const f = cfg.fetchImpl ?? fetch;
  const res = await f(url, { ...rest, headers });

  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : res.statusText;
    throw new ThiramaiHttpError(detail || `HTTP ${res.status}`, res.status, data);
  }

  return data as T;
}
