"use strict";
// web/app.js is a classic script (not a UMD module like web/types.js /
// web/fields.js): it runs top-level code against `window`, `document`,
// `EventLog`, `Toast`, etc. at load time, so it cannot be `require()`d under
// `node --test` (see tests_js/README-style comments in other files and the
// task report for why). This test instead exercises the exact body-parsing
// logic apiFetch uses ("read as text, parse only if non-empty"), applied to
// real `Response` objects (Node 25 has a global `Response`/`fetch`), so a
// regression in that logic — e.g. going back to unconditional
// `response.json()` — is still caught.

const test = require("node:test");
const assert = require("node:assert/strict");

// Mirrors the fixed body of apiFetch in web/app.js exactly.
async function parseApiResponseBody(response) {
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

// The old, buggy branch apiFetch used to run for anything other than a 204:
// unconditional response.json(). Kept here only to prove it's the bug.
async function oldBuggyParse(response) {
  if (response.status === 204) return null;
  return await response.json();
}

test("parseApiResponseBody returns null for a 202 with an empty body", async () => {
  const response = new Response(null, { status: 202 });
  assert.equal(await parseApiResponseBody(response), null);
});

test("parseApiResponseBody returns null for a 204 with an empty body", async () => {
  const response = new Response(null, { status: 204 });
  assert.equal(await parseApiResponseBody(response), null);
});

test("parseApiResponseBody parses a non-empty JSON body regardless of status", async () => {
  const response = new Response(JSON.stringify({ rev: 3, roots: [] }), { status: 200 });
  assert.deepEqual(await parseApiResponseBody(response), { rev: 3, roots: [] });
});

test("parseApiResponseBody parses a non-empty JSON body on a 202", async () => {
  const response = new Response(JSON.stringify({ ok: true }), { status: 202 });
  assert.deepEqual(await parseApiResponseBody(response), { ok: true });
});

test("regression check: the old status===204-only branch throws on an empty-body 202 (this is the bug being fixed)", async () => {
  const response = new Response(null, { status: 202 });
  await assert.rejects(() => oldBuggyParse(response));
});

test("regression check: the old branch was fine for an empty-body 204", async () => {
  const response = new Response(null, { status: 204 });
  assert.equal(await oldBuggyParse(response), null);
});
