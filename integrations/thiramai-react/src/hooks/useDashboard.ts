"use client";

import * as React from "react";
import { thiramaiFetchJson, ThiramaiHttpError } from "../client";
import { useThiramaiConfig } from "../context";
import type { EmpireFinancialSummary, EmpireForecast } from "../types";

export type UseDashboardResult = {
  financial: EmpireFinancialSummary | null;
  forecast: EmpireForecast | null;
  loading: boolean;
  error: string | null;
  /** Parallel fetch: GET /empire/financial-summary + GET /empire/forecast */
  refresh: () => Promise<void>;
};

/**
 * Owner/Manager dashboard data (requires JWT with owner or manager role).
 */
export function useDashboard(): UseDashboardResult {
  const cfg = useThiramaiConfig();
  const [financial, setFinancial] = React.useState<EmpireFinancialSummary | null>(null);
  const [forecast, setForecast] = React.useState<EmpireForecast | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [fin, fc] = await Promise.all([
        thiramaiFetchJson<EmpireFinancialSummary>(cfg, "/empire/financial-summary", {
          method: "GET",
        }),
        thiramaiFetchJson<EmpireForecast>(cfg, "/empire/forecast", { method: "GET" }),
      ]);
      setFinancial(fin);
      setForecast(fc);
    } catch (e) {
      const msg =
        e instanceof ThiramaiHttpError
          ? e.message
          : e instanceof Error
            ? e.message
            : "Dashboard request failed.";
      setError(msg);
      setFinancial(null);
      setForecast(null);
    } finally {
      setLoading(false);
    }
  }, [cfg]);

  return { financial, forecast, loading, error, refresh };
}
