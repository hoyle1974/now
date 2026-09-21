"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ItemForm = require("../web/item-form.js");
const TypesData = require("../web/types-data.js");

test("every registry field except title has an input group in the item form", () => {
  for (const [name, spec] of Object.entries(TypesData)) {
    for (const field of spec.fields.filter((f) => f !== "title")) {
      assert.ok(ItemForm.FIELD_GROUPS.includes(field), `${name}.${field} has no input group`);
    }
  }
});

test("every registry icon exists in the icon set", () => {
  const src = fs.readFileSync(path.join(__dirname, "../web/ui-helpers.js"), "utf8");
  const set = new Set([...src.slice(src.indexOf("const ICONS")).matchAll(/^\s{2}([a-z]+):/gm)].map((m) => m[1]));
  for (const [name, spec] of Object.entries(TypesData)) assert.ok(set.has(spec.icon), `${name} icon ${spec.icon}`);
});
