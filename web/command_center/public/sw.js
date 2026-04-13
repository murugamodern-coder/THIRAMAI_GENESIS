/* THIRAMAI Command Center — cache shell + offline + Web Push */
const CACHE = "thiramai-cc-v3";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) =>
        cache.addAll([
          new Request("./offline.html", { cache: "reload" }),
          new Request("./manifest.json", { cache: "reload" }),
          new Request("./index.html", { cache: "reload" }),
        ]),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("push", (event) => {
  let payload = { title: "THIRAMAI", body: "", tag: "thiramai-default", data: {} };
  try {
    const raw = event.data?.text();
    if (raw) {
      const j = JSON.parse(raw);
      payload = {
        title: j.title || payload.title,
        body: j.body || "",
        tag: j.tag || payload.tag,
        data: typeof j.data === "object" && j.data !== null ? j.data : {},
      };
    }
  } catch (_) {
    /* ignore malformed */
  }
  const iconUrl = new URL("./thiramai-icon-192.png", self.location).href;
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: iconUrl,
      badge: iconUrl,
      tag: payload.tag,
      data: payload.data,
      vibrate: [80, 40, 80],
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  let url =
    typeof data.url === "string" && data.url.length > 0
      ? data.url
      : "/static/command_center/index.html#/today";
  if (url.startsWith("/")) {
    url = `${self.location.origin}${url}`;
  }
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        try {
          if (client.url.includes("command_center") && "focus" in client) {
            return client.focus();
          }
        } catch (_) {
          /* continue */
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    }),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(request, copy));
          }
          return res;
        })
        .catch(() =>
          caches.match("./index.html").then((cached) => cached || caches.match("./offline.html")),
        ),
    );
    return;
  }

  const url = new URL(request.url);
  if (url.pathname.startsWith("/static/command_center/") && !url.pathname.includes("index.html")) {
    event.respondWith(
      caches.match(request).then((hit) => {
        if (hit) return hit;
        return fetch(request).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(request, copy));
          }
          return res;
        });
      }),
    );
  }
});
