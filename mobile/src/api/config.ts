import Constants from "expo-constants";

export function getApiBaseUrl(): string {
  const fromExtra = Constants.expoConfig?.extra?.apiUrl as string | undefined;
  if (fromExtra && typeof fromExtra === "string" && fromExtra.length > 0) {
    return fromExtra.replace(/\/$/, "");
  }
  return "http://127.0.0.1:8000";
}
