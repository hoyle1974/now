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
  const known = (item) => Boolean(item) && Object.hasOwn(data, item.type);
  const get = (item) => data[known(item) ? item.type : DEFAULT];
  const can = (item, flag) => Boolean(get(item)[flag]);
  const nameOf = (item) => (known(item) ? item.type : DEFAULT);
  const hasField = (item, field) => get(item).fields.includes(field);

  // Progress over the todos beneath each item: only types with a checkbox count, at any
  // depth, so a container (list/project) is looked through, never counted itself.
  // Returns Map(id -> { total, done }).
  function descendantCounts(todosById) {
    const counts = new Map();
    const countFor = (id) => {
      if (counts.has(id)) return counts.get(id);
      const result = { total: 0, done: 0 };
      counts.set(id, result); // cycle guard
      for (const childId of todosById.get(id).child_ids) {
        const child = todosById.get(childId);
        if (!child) continue;
        const sub = countFor(childId);
        result.total += (can(child, "hasCheckbox") ? 1 : 0) + sub.total;
        result.done += (can(child, "hasCheckbox") && child.done ? 1 : 0) + sub.done;
      }
      return result;
    };
    for (const id of todosById.keys()) countFor(id);
    return counts;
  }

  return { get, can, hasField, nameOf, descendantCounts, names: Object.keys(data) };
});
