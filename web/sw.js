// Service worker for push reminders only: it shows what the server sends and
// focuses the app on tap. No caching or fetch handling, so it cannot interfere
// with the offline sync outbox. iOS revokes permission from a page that gets a
// push and shows nothing, so every push shows a notification.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Same shape handling as Push.parse in push.js.
function parse(raw) {
  const d = (raw && typeof raw === "object" && (raw.data || raw.notification)) || raw;
  const o = d && typeof d === "object" ? d : {};
  return { title: String(o.title || "Todos"), body: String(o.body || ""), url: String(o.url || "/") };
}

self.addEventListener("push", (event) => {
  let raw = null;
  try { raw = event.data ? event.data.json() : null; } catch (_) { /* not JSON */ }
  const n = parse(raw);
  event.waitUntil(self.registration.showNotification(n.title, {
    body: n.body,
    icon: "/icons/icon-192.png",
    data: { url: n.url },
  }));
});

self.addEventListener("notificationclick", (event) => {
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
