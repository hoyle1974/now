"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Markdown = require("../web/markdown.js");

test("renders markdown and escapes raw html", () => {
  const html = Markdown.render("Hello **world**\n\n<script>alert(1)</script>");
  assert.match(html, /<strong>world<\/strong>/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("does not turn a javascript url into a link", () => {
  const html = Markdown.render("[x](javascript:alert(1))");
  assert.doesNotMatch(html, /href\s*=\s*["']?\s*javascript:/i);
});
