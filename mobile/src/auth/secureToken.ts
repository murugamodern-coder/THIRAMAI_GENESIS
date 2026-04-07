import * as SecureStore from "expo-secure-store";

const ACCESS_KEY = "thiramai_access_token";
const REFRESH_KEY = "thiramai_refresh_token";

export async function saveTokens(access: string, refresh: string | null): Promise<void> {
  await SecureStore.setItemAsync(ACCESS_KEY, access, {
    keychainAccessible: SecureStore.WHEN_UNLOCKED,
  });
  if (refresh) {
    await SecureStore.setItemAsync(REFRESH_KEY, refresh, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED,
    });
  } else {
    await SecureStore.deleteItemAsync(REFRESH_KEY).catch(() => undefined);
  }
}

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_KEY);
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_KEY);
}

export async function clearTokens(): Promise<void> {
  await SecureStore.deleteItemAsync(ACCESS_KEY).catch(() => undefined);
  await SecureStore.deleteItemAsync(REFRESH_KEY).catch(() => undefined);
}
