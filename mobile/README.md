# THIRAMAI Mobile (React Native + Expo)

Connects to the THIRAMAI FastAPI backend: **`/personal/today`**, **`/personal/action`**, **`/personal/summary`**, and **`POST /auth/login`** for JWT.

## Setup

```bash
cd mobile
npm install
```

## API URL

- **Simulator / same machine:** default `http://127.0.0.1:8000` in `app.json` → `expo.extra.apiUrl`.
- **Physical device (same Wi‑Fi):** use your PC’s LAN IP, e.g.

  ```bash
  set EXPO_PUBLIC_API_URL=http://192.168.1.10:8000
  npx expo start
  ```

  (PowerShell: `$env:EXPO_PUBLIC_API_URL="http://..."`)

- **Android emulator:** often `http://10.0.2.2:8000` to reach the host machine.

Override is applied via `app.config.js` + `EXPO_PUBLIC_API_URL`.

Ensure the backend allows your device origin if you use CORS for web; native apps are not browser CORS-limited.

## Run

```bash
npx expo start
```

Then open in **Expo Go** (scan QR) or press `a` / `i` for emulator.

## Features

- JWT login (`username` = email, OAuth2-style form to `/auth/login`)
- Tokens in **Expo SecureStore** (Keychain / EncryptedSharedPreferences)
- **Pull to refresh** on Today, Actions, Summary
- Three tabs: **Today** (focus, alerts, streak, score), **Actions** (Run on `api_call` suggestions), **Summary** (evening block)
- **Background refresh:** while the app is open, Today data refetches when the app returns to the foreground and about every 90 seconds when active.
- **Local alerts:** optional switch on Today — schedules a **local** notification when the number of guidance alerts increases (uses `expo-notifications`). This is not FCM/APNs remote push; for production remote push you need Expo push credentials and a backend sender.

Replace placeholder icons in `assets/` before store release.
