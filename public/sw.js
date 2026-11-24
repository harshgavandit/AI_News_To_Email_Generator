/* Informa AI service worker: an offline page for navigations, and device alerts.
 * It never caches news, API responses or scripts, so readers always get the current site. */
const CACHE = "informa-shell-v1";
const SHELL = ["/offline.html", "/offline.css", "/offline.js", "/icons/icon-192.png", "/informa-ai-icon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key.startsWith("informa-") && key !== CACHE).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (SHELL.includes(url.pathname)) {
    event.respondWith(fetch(request).catch(() => caches.match(url.pathname)));
    return;
  }
  if (request.mode !== "navigate") return;
  event.respondWith(fetch(request).catch(async () => (await caches.match("/offline.html")) ||
    new Response("You're offline.", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } })));
});

function safeUrl(value, origin) {
  try {
    const url = new URL(value || "/", origin);
    return url.origin === origin ? url.pathname + url.search + url.hash : "/";
  } catch { return "/"; }
}

function notificationFrom(data) {
  const message = data && typeof data === "object" ? data : {};
  const text = (value, limit) => (typeof value === "string" ? value : "").slice(0, limit);
  return {
    title: text(message.title, 140) || "Informa AI",
    options: { body: text(message.body, 240), tag: text(message.tag, 80) || "informa-update",
      icon: "/icons/icon-192.png", badge: "/icons/badge-96.png", renotify: false,
      data: { url: safeUrl(message.url, self.location.origin) } },
  };
}

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data?.text?.() || "" }; }
  const { title, options } = notificationFrom(data);
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(safeUrl(event.notification.data?.url, self.location.origin), self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const open = windows.find((client) => client.url === target);
    if (open) return open.focus();
    return self.clients.openWindow(target);
  }));
});

// Browsers occasionally replace a push address; carry the reader's alerts over to the new one.
self.addEventListener("pushsubscriptionchange", (event) => {
  const previous = event.oldSubscription;
  event.waitUntil((async () => {
    const next = event.newSubscription || (previous?.options?.applicationServerKey &&
      await self.registration.pushManager.subscribe({ userVisibleOnly: true,
        applicationServerKey: previous.options.applicationServerKey }));
    if (!previous || !next) return;
    await fetch("/api/push/subscription/rotate", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_endpoint: previous.endpoint, subscription: next.toJSON() }) });
  })().catch(() => undefined));
});
