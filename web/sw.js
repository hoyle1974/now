// Service worker: shows push reminders and keeps an offline app shell.
// The shell cache exists so the app can LAUNCH with no signal; edits made offline
// are handled by the sync outbox, not here. Only the page, its versioned assets,
// the icons and the Firebase SDK are cached: API calls (/todos, /push, /calendar,
// attachments) always go to the network untouched. iOS revokes permission from a
// page that gets a push and shows nothing, so every push shows a notification.

// Registered as /sw.js?v=<app version>: each release is a new worker with its own
// cache, and activate drops the old ones.
// False under `node --test`, where only the pure helpers are exercised.
const IN_WORKER = typeof self !== "undefined" && typeof self.addEventListener === "function";
const VERSION = (typeof self !== "undefined" && self.location
  ? new URL(self.location.href).searchParams.get("v") : null) || "0";
const CACHE = "shell-" + VERSION;
const SDK_HOST = "www.gstatic.com";
const PAGE_WAIT_MS = 3000;

// "versioned": URL carries ?v=, so its content never changes: cache first.
// "fresh": the page and unversioned files: network first, cache when offline.
// null: not ours, leave to the browser.
function strategy(url, origin) {
  if (url.origin === origin) {
    if (url.searchParams.has("v") && /\.(js|css)$/.test(url.pathname)) return "versioned";
    if (url.pathname === "/" || url.pathname === "/index.html" || url.pathname === "/manifest.json" ||
        url.pathname === "/favicon.ico" || url.pathname.startsWith("/icons/") ||
        url.pathname.startsWith("/splash/")) return "fresh";
    return null;
  }
  return url.hostname === SDK_HOST && url.pathname.startsWith("/firebasejs/") ? "versioned" : null;
}

if (typeof module === "object" && module.exports) module.exports = { strategy };

if (IN_WORKER) {
  self.addEventListener("install", () => self.skipWaiting());
  self.addEventListener("activate", (event) => event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key.startsWith("shell-") && key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })()));

  async function put(request, response) {
    // Opaque (cross-origin script) responses report ok=false but are cacheable.
    if (response && (response.ok || response.type === "opaque")) {
      try { await (await caches.open(CACHE)).put(request, response.clone()); } catch (_) { /* quota */ }
    }
    return response;
  }

  async function cacheFirst(request) {
    const hit = await caches.match(request);
    return hit || put(request, await fetch(request));
  }

  async function networkFirst(request) {
    try {
      const timeout = new Promise((_, reject) => setTimeout(reject, PAGE_WAIT_MS, new Error("slow")));
      return await put(request, await Promise.race([fetch(request), timeout]));
    } catch (e) {
      const hit = await caches.match(request);
      if (hit) return hit;
      throw e;
    }
  }

  self.addEventListener("fetch", (event) => {
    const req = event.request;
    if (req.method !== "GET") return;
    const how = strategy(new URL(req.url), self.location.origin);
    if (how === "versioned") event.respondWith(cacheFirst(req));
    else if (how === "fresh") event.respondWith(networkFirst(req));
  });
}

// Same shape handling as Push.parse in push.js.
function parse(raw) {
  const d = (raw && typeof raw === "object" && (raw.data || raw.notification)) || raw;
  const o = d && typeof d === "object" ? d : {};
  return { title: String(o.title || "Todos"), body: String(o.body || ""), url: String(o.url || "/") };
}

if (IN_WORKER) self.addEventListener("push", (event) => {
  let raw = null;
  try { raw = event.data ? event.data.json() : null; } catch (_) { /* not JSON */ }
  const n = parse(raw);
  event.waitUntil(self.registration.showNotification(n.title, {
    body: n.body,
    icon: "/icons/icon-192.png",
    data: { url: n.url },
  }));
});

if (IN_WORKER) self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of open) {
      if ("focus" in client) { await client.focus(); return; }
    }
    await self.clients.openWindow(url);
  })());
});
