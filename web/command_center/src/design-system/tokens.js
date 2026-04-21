export const colors = {
  brand: {
    primary: "#6366F1",
    primaryDark: "#4F46E5",
    primaryLight: "#A5B4FC",
    success: "#10B981",
    warning: "#F59E0B",
    error: "#EF4444",
    info: "#3B82F6",
  },
  light: {
    background: "#FFFFFF",
    surface: "#F8FAFC",
    surface2: "#F1F5F9",
    border: "#E2E8F0",
    textPrimary: "#0F172A",
    textSecondary: "#64748B",
    textMuted: "#94A3B8",
  },
  dark: {
    background: "#0A0A0F",
    surface: "#111827",
    surface2: "#1F2937",
    border: "#374151",
    textPrimary: "#F9FAFB",
    textSecondary: "#9CA3AF",
    textMuted: "#6B7280",
  },
};

export const typography = {
  fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",
  display: { size: "48px", lineHeight: "56px", weight: 700 },
  h1: { size: "36px", lineHeight: "44px", weight: 700 },
  h2: { size: "28px", lineHeight: "36px", weight: 600 },
  h3: { size: "22px", lineHeight: "30px", weight: 600 },
  h4: { size: "18px", lineHeight: "26px", weight: 600 },
  bodyLg: { size: "16px", lineHeight: "24px", weight: 400 },
  body: { size: "14px", lineHeight: "22px", weight: 400 },
  caption: { size: "12px", lineHeight: "18px", weight: 400 },
  label: { size: "11px", lineHeight: "16px", weight: 600, transform: "uppercase" },
};

export const spacing = {
  xs: "4px",
  sm: "8px",
  md: "16px",
  lg: "24px",
  xl: "32px",
  "2xl": "48px",
  "3xl": "64px",
};

export const radius = {
  sm: "6px",
  md: "10px",
  lg: "16px",
  xl: "24px",
  full: "9999px",
};

export const shadows = {
  sm: "0 1px 3px rgba(0,0,0,0.08)",
  md: "0 4px 16px rgba(0,0,0,0.12)",
  lg: "0 8px 32px rgba(0,0,0,0.16)",
  glow: "0 0 24px rgba(99,102,241,0.3)",
};

export const motion = {
  fast: "100ms",
  normal: "200ms",
  slow: "300ms",
  ease: "cubic-bezier(0.2, 0.8, 0.2, 1)",
};

export const tokens = {
  colors,
  typography,
  spacing,
  radius,
  shadows,
  motion,
};

export default tokens;
