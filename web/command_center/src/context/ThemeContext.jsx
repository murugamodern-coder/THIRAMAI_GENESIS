import { createContext, useCallback, useContext, useEffect, useState } from "react";

const THEME_KEY = "thiramai_cc_theme";
const ThemeContext = createContext(null);

function getSystemTheme() {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function resolveInitialTheme() {
  if (typeof window === "undefined") return "light";
  const saved = window.localStorage.getItem(THEME_KEY);
  if (saved === "light" || saved === "dark" || saved === "system") return saved;
  return "system";
}

export function ThemeProvider({ children }) {
  const [mode, setMode] = useState(resolveInitialTheme);
  const [systemTheme, setSystemTheme] = useState(getSystemTheme);

  const theme = mode === "system" ? systemTheme : mode;

  const toggleTheme = useCallback(() => {
    setMode((prev) =>
      prev === "dark" || (prev === "system" && systemTheme === "dark") ? "light" : "dark",
    );
  }, [systemTheme]);

  const value = { mode, theme, setMode, toggleTheme };

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const handle = () => setSystemTheme(media.matches ? "dark" : "light");
    if (media.addEventListener) media.addEventListener("change", handle);
    else media.addListener(handle);
    return () => {
      if (media.removeEventListener) media.removeEventListener("change", handle);
      else media.removeListener(handle);
    };
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.style.colorScheme = theme;
  }, [theme]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(THEME_KEY, mode);
  }, [mode]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return context;
}
