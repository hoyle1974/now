const test = require("node:test");
const assert = require("node:assert");
const { strategy } = require("../web/sw.js");

const ORIGIN = "https://now.example.app";
const kind = (path, origin = ORIGIN) => strategy(new URL(path, origin), ORIGIN);

test("versioned assets and the Firebase SDK are cache-first", () => {
  assert.equal(kind("/app.js?v=70"), "versioned");
  assert.equal(kind("/style.css?v=70"), "versioned");
  assert.equal(kind("https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js", "https://www.gstatic.com"), "versioned");
});

test("the page and static files are network-first", () => {
  for (const p of ["/", "/index.html", "/manifest.json", "/favicon.ico", "/icons/icon-192.png", "/splash/402x874@3-dark.png"]) {
    assert.equal(kind(p), "fresh", p);
  }
});

test("API and other routes are never handled", () => {
  for (const p of ["/todos", "/todos/abc/attachments/x", "/push/devices", "/calendar/link", "/calendar/x.ics", "/health", "/todos?v=1", "/internal/notify", "/__/auth/handler"]) {
    assert.equal(kind(p), null, p);
  }
  assert.equal(kind("https://evil.example/firebasejs/x.js", "https://evil.example"), null);
  assert.equal(kind("https://www.gstatic.com/other.js", "https://www.gstatic.com"), null);
});
