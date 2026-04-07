/**
 * Optional local notification when Personal alerts change (no remote push server).
 * Best-effort: skips if expo-notifications is unavailable or permission denied.
 */

import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

let configured = false;

async function ensureAndroidChannel() {
  if (configured) return;
  configured = true;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
  if (typeof Notifications.setNotificationChannelAsync === "function") {
    await Notifications.setNotificationChannelAsync("thiramai-today", {
      name: "THIRAMAI Today",
      importance: Notifications.AndroidImportance.DEFAULT,
    });
  }
}

export async function requestAlertPermission(): Promise<boolean> {
  try {
    await ensureAndroidChannel();
    const { status: existing } = await Notifications.getPermissionsAsync();
    if (existing === "granted") return true;
    const { status } = await Notifications.requestPermissionsAsync();
    return status === "granted";
  } catch {
    return false;
  }
}

export async function presentFirstAlertLine(body: string): Promise<void> {
  const line = (body || "").trim().slice(0, 220);
  if (!line) return;
  try {
    await ensureAndroidChannel();
    await Notifications.scheduleNotificationAsync({
      content: {
        title: "THIRAMAI",
        body: line,
        sound: false,
        ...(Platform.OS === "android"
          ? { android: { channelId: "thiramai-today" } }
          : {}),
      },
      trigger: null,
    });
  } catch {
    /* ignore */
  }
}
