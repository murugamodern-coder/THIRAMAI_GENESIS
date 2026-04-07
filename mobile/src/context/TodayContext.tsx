import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AppState, type AppStateStatus } from "react-native";
import { fetchPersonalToday } from "../api/client";
import type { PersonalTodayResponse } from "../api/types";

type TodayCtx = {
  today: PersonalTodayResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

const TodayContext = createContext<TodayCtx | null>(null);

export function TodayProvider({
  token,
  children,
}: {
  token: string;
  children: React.ReactNode;
}) {
  const [today, setToday] = useState<PersonalTodayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPersonalToday(token);
      setToday(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setToday(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (next: AppStateStatus) => {
      if (next === "active") void refresh();
    });
    const iv = setInterval(() => {
      if (AppState.currentState === "active") void refresh();
    }, 90_000);
    return () => {
      sub.remove();
      clearInterval(iv);
    };
  }, [refresh]);

  const value = useMemo(
    () => ({ today, loading, error, refresh }),
    [today, loading, error, refresh]
  );

  return <TodayContext.Provider value={value}>{children}</TodayContext.Provider>;
}

export function useToday(): TodayCtx {
  const ctx = useContext(TodayContext);
  if (!ctx) throw new Error("useToday outside TodayProvider");
  return ctx;
}
