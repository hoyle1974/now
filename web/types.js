// Item types on the client: what a row of each type can do, from the registry data
// generated out of app/types.json. Feature code asks Types.can(item, flag) and never
// compares a type name. A missing or unknown type behaves as "todo".
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./types-data.js"));
  } else {
    root.Types = factory(root.TypesData);
  }
})(typeof self !== "undefined" ? self : this, function (data) {
  "use strict";

  const DEFAULT = "todo";
  const get = (item) => data[item && item.type] || data[DEFAULT];
  const can = (item, flag) => Boolean(get(item)[flag]);
  const hasField = (item, field) => get(item).fields.includes(field);

  return { get, can, hasField, names: Object.keys(data) };
});
