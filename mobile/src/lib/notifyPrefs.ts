import * as SecureStore from "expo-secure-store";

const KEY = "thiramai_notify_alerts";

export async function getNotifyAlertsEnabled(): Promise<boolean> {
  try {
    const v = await SecureStore.getItemAsync(KEY);
    return v === "1";
  } catch {
    return false;
  }
}

export async function setNotifyAlertsEnabled(on: boolean): Promise<void> {
  await SecureStore.setItemAsync(KEY, on ? "1" : "0", {
    keychainAccessible: SecureStore.WHEN_UNLOCKED,
  });
}
