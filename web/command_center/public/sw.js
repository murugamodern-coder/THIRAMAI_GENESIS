const APP_PREFIX = "/static/command_center/";
const SW_VERSION = "v1";
const SHELL_CACHE = `thiramai-shell-${SW_VERSION}`;
const RUNTIME_CACHE = `thiramai-runtime-${SW_VERSION}`;
const OFFLINE_URL = `${APP_PREFIX}offline.html`;
const SHELL_URLS = [
  `${APP_PREFIX}index.html`,
  `${APP_PREFIX}manifest.json`,
  `${APP_PREFIX}thiramai-icon-192.png`,
  `${APP_PREFIX}thiramai-icon-512.png`,
  OFFLINE_URL,
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("thiramai-") && ![SHELL_CACHE, RUNTIME_CACHE].includes(k))
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(async () => {
          const cachedRoute = await caches.match(req);
          if (cachedRoute) return cachedRoute;
          const appShell = await caches.match(`${APP_PREFIX}index.html`);
          if (appShell) return appShell;
          const offline = await caches.match(OFFLINE_URL);
          return (
            offline ||
            new Response("Offline", {
              status: 503,
              statusText: "Offline",
              headers: { "Content-Type": "text/plain; charset=utf-8" },
            })
          );
        }),
    );
    return;
  }

  if (url.pathname.startsWith(APP_PREFIX)) {
    event.respondWith(
      caches.match(req).then((hit) => {
        if (hit) return hit;
        return fetch(req)
          .then((res) => {
            const copy = res.clone();
            caches.open(RUNTIME_CACHE).then((c) => c.put(req, copy)).catch(() => {});
            return res;
          })
          .catch(() => caches.match(OFFLINE_URL));
      }),
    );
  }
});
