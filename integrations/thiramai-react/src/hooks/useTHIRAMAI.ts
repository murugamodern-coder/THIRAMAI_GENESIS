"use client";

import * as React from "react";
import { thiramaiFetchJson, ThiramaiHttpError } from "../client";
import { useThiramaiConfig } from "../context";
import type { ChatResponse } from "../types";

/** Matches server `MAX_USER_MESSAGE_CHARS` (core.policies.loader). */
export const THIRAMAI_MAX_CHAT_CHARS = 5000;

export type UseTHIRAMAIResult = {
  /** Send a chat message; uses GET /chat?query=… with Bearer token */
  sendChat: (query: string) => Promise<ChatResponse | null>;
  loading: boolean;
  error: string | null;
  lastResponse: ChatResponse | null;
  clearError: () => void;
};

/**
 * AI council chat — authenticated with the token from {@link ThiramaiProvider}.
 */
export function useTHIRAMAI(): UseTHIRAMAIResult {
  const cfg = useThiramaiConfig();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [lastResponse, setLastResponse] = React.useState<ChatResponse | null>(null);

  const clearError = React.useCallback(() => setError(null), []);

  const sendChat = React.useCallback(
    async (query: string) => {
      const q = query.trim();
      if (!q) {
        setError("Message cannot be empty.");
        return null;
      }
      if (q.length > THIRAMAI_MAX_CHAT_CHARS) {
        setError(`Message exceeds ${THIRAMAI_MAX_CHAT_CHARS} characters.`);
        return null;
      }

      setLoading(true);
      setError(null);
      try {
        const data = await thiramaiFetchJson<ChatResponse>(cfg, "/chat", {
          method: "GET",
          searchParams: { query: q },
        });
        setLastResponse(data);
        return data;
      } catch (e) {
        const msg =
          e instanceof ThiramaiHttpError
            ? e.message
            : e instanceof Error
              ? e.message
              : "Chat request failed.";
        setError(msg);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [cfg]
  );

  return { sendChat, loading, error, lastResponse, clearError };
}
