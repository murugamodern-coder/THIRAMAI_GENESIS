import api from "../api/client.js";

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export async function fetchPushVapidPublicKey() {
  const { data } = await api.get("/push/vapid-public-key");
  const k = data?.public_key;
  if (!k || typeof k !== "string") {
    throw new Error("Server did not return VAPID public key");
  }
  return k;
}

/**
 * Ensure service worker is active, subscribe with VAPID, POST /push/subscribe.
 * Call after Notification permission is granted (required on most browsers).
 */
export async function registerWebPushSubscription() {
  if (typeof window === "undefined") {
    throw new Error("Push requires a browser");
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    throw new Error("Web Push not supported in this browser");
  }

  const perm = Notification.permission;
  if (perm === "denied") {
    throw new Error("Notifications blocked — enable them in browser settings");
  }
  if (perm !== "granted") {
    const p = await Notification.requestPermission();
    if (p !== "granted") {
      throw new Error("Notification permission required for push");
    }
  }

  const publicKey = await fetchPushVapidPublicKey();
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
  }
  const j = sub.toJSON();
  if (!j.endpoint || !j.keys?.p256dh || !j.keys?.auth) {
    throw new Error("Invalid push subscription from browser");
  }
  await api.post("/push/subscribe", {
    endpoint: j.endpoint,
    keys: { p256dh: j.keys.p256dh, auth: j.keys.auth },
  });
  return sub;
}

export async function unregisterWebPushSubscription() {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
    return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  const j = sub.toJSON();
  try {
    await api.post("/push/unsubscribe", { endpoint: j.endpoint });
  } catch {
    /* still try unsubscribe locally */
  }
  await sub.unsubscribe();
}
