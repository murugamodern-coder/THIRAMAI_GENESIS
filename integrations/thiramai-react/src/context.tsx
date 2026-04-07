"use client";

import * as React from "react";
import type { ThiramaiClientConfig } from "./client";

export const ThiramaiConfigContext = React.createContext<ThiramaiClientConfig | null>(null);

export type ThiramaiProviderProps = {
  children: React.ReactNode;
  baseUrl: string;
  getAccessToken: ThiramaiClientConfig["getAccessToken"];
  fetchImpl?: ThiramaiClientConfig["fetchImpl"];
};

/**
 * Wrap your app (or dashboard subtree) and supply API base URL + token resolver.
 *
 * @example Next.js
 * ```tsx
 * <ThiramaiProvider
 *   baseUrl={process.env.NEXT_PUBLIC_THIRAMAI_URL!}
 *   getAccessToken={() => typeof window !== 'undefined' ? localStorage.getItem('access_token') : null}
 * >
 *   {children}
 * </ThiramaiProvider>
 * ```
 */
export function ThiramaiProvider({
  children,
  baseUrl,
  getAccessToken,
  fetchImpl,
}: ThiramaiProviderProps) {
  const value = React.useMemo<ThiramaiClientConfig>(
    () => ({
      baseUrl,
      getAccessToken,
      fetchImpl,
    }),
    [baseUrl, getAccessToken, fetchImpl]
  );

  return (
    <ThiramaiConfigContext.Provider value={value}>{children}</ThiramaiConfigContext.Provider>
  );
}

export function useThiramaiConfig(): ThiramaiClientConfig {
  const ctx = React.useContext(ThiramaiConfigContext);
  if (!ctx) {
    throw new Error("useThiramaiConfig must be used within <ThiramaiProvider>");
  }
  return ctx;
}
