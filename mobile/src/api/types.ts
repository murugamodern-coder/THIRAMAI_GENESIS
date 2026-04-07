export type Guidance = {
  top_focus?: string;
  focus?: string;
  alerts?: string[];
  actionable_suggestions?: ActionableSuggestion[];
  secondary?: string[];
  low_priority?: string[];
};

export type ActionableSuggestion = {
  text?: string;
  action?: string;
  action_type?: string;
  endpoint?: string;
  method?: string;
  body?: Record<string, unknown>;
};

export type PersonalTodayResponse = {
  authenticated?: boolean;
  streak_days?: number;
  daily_score?: number;
  guidance?: Guidance;
  tasks?: { id?: number; title?: string }[];
};

export type EveningSummary = {
  summary?: string;
  wins?: string[];
  carry_over?: string[];
  tomorrow_hint?: string;
};

export type PersonalSummaryResponse = {
  ok?: boolean;
  streak_days?: number;
  daily_score?: number;
  evening?: EveningSummary;
};

export type TokenResponse = {
  access_token: string;
  token_type?: string;
  expires_in?: number;
  refresh_token?: string | null;
};
