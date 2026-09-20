"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Push = require("../web/push.js");

const env = (o) => ({ hasSW: true, hasPush: true, hasNotification: true, permission: "default", enabled: false, ...o });

test("status: unsupported without service worker, push or notifications", () => {
  assert.equal(Push.status(env({ hasSW: false })), "unsupported");
  assert.equal(Push.status(env({ hasPush: false })), "unsupported");
  assert.equal(Push.status(env({ hasNotification: false })), "unsupported");
});

test("status: blocked, off and on", () => {
  assert.equal(Push.status(env({ permission: "denied" })), "blocked");
  assert.equal(Push.status(env({ permission: "default" })), "off");
  assert.equal(Push.status(env({ permission: "granted", enabled: false })), "off");
  assert.equal(Push.status(env({ permission: "granted", enabled: true })), "on");
});

test("registerBody carries token, timezone and platform", () => {
  assert.deepEqual(Push.registerBody("tok", "America/Los_Angeles", "ios"),
    { token: "tok", tz: "America/Los_Angeles", platform: "ios" });
});

test("parse reads FCM data payloads, bare objects and garbage", () => {
  assert.deepEqual(Push.parse({ data: { title: "2 due today", body: "a, b", url: "/x" } }),
    { title: "2 due today", body: "a, b", url: "/x" });
  assert.deepEqual(Push.parse({ title: "T", body: "B" }), { title: "T", body: "B", url: "/" });
  assert.deepEqual(Push.parse(null), { title: "Todos", body: "", url: "/" });
  assert.deepEqual(Push.parse("nonsense"), { title: "Todos", body: "", url: "/" });
});
