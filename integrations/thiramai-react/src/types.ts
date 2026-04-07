/**
 * Response shapes aligned with FastAPI JSON (api/routes/ai_chat, factory, empire, analytics).
 */

export type QuickAction = {
  label: string;
  url: string;
  kind: string;
};

export type ChatResponse = {
  narrative: string;
  action_intent: Record<string, unknown>;
  response: string;
  quick_actions: QuickAction[];
};

export type EmpireFinancialSummary = {
  organization_id: number;
  total_revenue_inr: number;
  revenue_note: string;
  pending_debts_principal_inr: number;
  pending_debts_note: string;
  production_costs_inr: number;
  production_costs_note: string;
  production_log_row_count: number;
};

/** predictive_engine.compute_forecasts — partial; extend as needed */
export type EmpireForecast = {
  organization_id: number;
  generated_at_utc?: string;
  target_next_month?: {
    start: string;
    end: string;
    label: string;
  };
  revenue_inr?: {
    forecast_next_month_inr?: number;
    moving_average_next_inr?: number;
    linear_trend_next_inr?: number;
    method?: string;
    historical_months?: string[];
    values?: number[];
  };
  production_inventory_index?: {
    forecast_next_month_index?: number;
    description?: string;
    method?: string;
    historical_months?: string[];
    values?: number[];
  };
  disclaimer?: string;
  data_quality?: Record<string, unknown>;
  ok?: boolean;
  error?: string;
};

/** workers.alert_system → list_active_alerts_for_organization item */
export type Stage4AlertItem = {
  id: number;
  kind: string;
  severity: string;
  title: string;
  body: string;
  created_at_utc: string | null;
  reference_type: string | null;
  reference_id: number | null;
  dedupe_key: string;
};

export type ActiveAlertsPayload = {
  ok: boolean;
  organization_id?: number;
  unread_count: number;
  items: Stage4AlertItem[];
  reason?: string;
};

export type MasterDashboardResponse = {
  schema: string;
  control_tower?: boolean;
  organization_id: number;
  generated_at_utc: string;
  active_alerts: ActiveAlertsPayload;
  revenue?: Record<string, unknown>;
  pending_approvals?: Record<string, unknown>;
  ai_forecast?: Record<string, unknown>;
};

export type ThiramaiClientError = {
  status: number;
  message: string;
  body?: unknown;
};
