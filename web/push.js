// Reminders: web push through Firebase Cloud Messaging. The pure helpers run
// under `node --test`; enable/refresh/disable need a browser. The server sends
// one daily digest (see app/push.py); this only registers the
// device. Nothing here may break the app: callers catch every failure.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(root);
  } else {
    root.Push = factory(root);
  }
})(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";

  const FLAG = "now.push";
  // Optional Web Push certificate key from the Firebase console. Empty = FCM's default.
  const VAPID_KEY = "";

  function status(env) {
    if (!env.hasSW || !env.hasPush || !env.hasNotification) return "unsupported";
    if (env.permission === "denied") return "blocked";
    return env.permission === "granted" && env.enabled ? "on" : "off";
  }

  function registerBody(token, tz, platform) {
    return { token, tz, platform };
  }

  // The service worker keeps its own copy of this; keep them in step.
  function parse(raw) {
    const d = (raw && typeof raw === "object" && (raw.data || raw.notification)) || raw;
    const o = d && typeof d === "object" ? d : {};
    return { title: String(o.title || "Todos"), body: String(o.body || ""), url: String(o.url || "/") };
  }

  const read = () => { try { return root.localStorage.getItem(FLAG) === "1"; } catch (_) { return false; } };
  const write = (on) => {
    try { on ? root.localStorage.setItem(FLAG, "1") : root.localStorage.removeItem(FLAG); } catch (_) { /* unavailable */ }
  };

  const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const platform = () => (/iPhone|iPad|iPod/.test(root.navigator.userAgent) ? "ios" : "web");

  async function token() {
    const reg = await root.navigator.serviceWorker.register("/sw.js");
    await root.navigator.serviceWorker.ready;
    const opts = { serviceWorkerRegistration: reg };
    if (VAPID_KEY) opts.vapidKey = VAPID_KEY;
    return root.firebase.messaging().getToken(opts);
  }

  // Register (or refresh) this device's token and timezone. Cheap: run at launch.
  async function refresh() {
    const t = await token();
    if (!t) throw new Error("no push token");
    const res = await root.fetch("/push/devices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(registerBody(t, tz(), platform())),
    });
    if (!res.ok) throw new Error("register " + res.status);
    write(true);
    return t;
  }

  // Must run from a tap: iOS only shows the permission prompt for a gesture.
  async function enable() {
    const permission = await root.Notification.requestPermission();
    if (permission !== "granted") return permission;
    await refresh();
    return "granted";
  }

  async function disable() {
    write(false);
    try {
      const t = await token();
      await root.fetch("/push/devices/unregister", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: t }),
      });
      await root.firebase.messaging().deleteToken();
    } catch (_) { /* the flag is already off; a stale token is pruned by the server */ }
  }

  return { status, registerBody, parse, enabled: read, refresh, enable, disable };
});
