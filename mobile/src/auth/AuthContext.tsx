import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { loginWithPassword } from "../api/client";
import { clearTokens, getAccessToken, saveTokens } from "./secureToken";

type AuthState = {
  token: string | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const t = await getAccessToken();
        if (!cancelled) setToken(t);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await loginWithPassword(email, password);
    await saveTokens(res.access_token, res.refresh_token ?? null);
    setToken(res.access_token);
  }, []);

  const logout = useCallback(async () => {
    await clearTokens();
    setToken(null);
  }, []);

  const value = useMemo(
    () => ({ token, ready, login, logout }),
    [token, ready, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
