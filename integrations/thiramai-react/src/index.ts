/**
 * THIRAMAI FastAPI integration for React / Next.js App Router.
 *
 * Backend routes used:
 * - GET /chat?query=…
 * - GET /empire/financial-summary
 * - GET /empire/forecast
 * - GET /analytics/master-dashboard (active_alerts → Stage 4 alert_system)
 */

export { ThiramaiProvider, useThiramaiConfig } from "./context";
export type { ThiramaiProviderProps } from "./context";

export {
  thiramaiFetchJson,
  resolveToken,
  ThiramaiHttpError,
} from "./client";
export type { ThiramaiClientConfig, GetToken } from "./client";

export { useTHIRAMAI, THIRAMAI_MAX_CHAT_CHARS } from "./hooks/useTHIRAMAI";
export type { UseTHIRAMAIResult } from "./hooks/useTHIRAMAI";

export { useDashboard } from "./hooks/useDashboard";
export type { UseDashboardResult } from "./hooks/useDashboard";

export { ThiramaiNotificationListener } from "./ThiramaiNotificationListener";
export type { ThiramaiNotificationListenerProps } from "./ThiramaiNotificationListener";

export type {
  ChatResponse,
  QuickAction,
  EmpireFinancialSummary,
  EmpireForecast,
  Stage4AlertItem,
  ActiveAlertsPayload,
  MasterDashboardResponse,
  ThiramaiClientError,
} from "./types";
