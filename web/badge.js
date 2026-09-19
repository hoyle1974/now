// Home-screen icon badge: the number of open todos due today or overdue.
// No DOM access, so it runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Badge = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // daysUntil(todo) is the app's calendar-day distance (negative = overdue).
  function dueCount(todos, daysUntil) {
    let n = 0;
    for (const t of todos) {
      if (!t.done && t.due_date && daysUntil(t) <= 0) n++;
    }
    return n;
  }

  // Sets or clears the badge. Never throws: the API is missing on many
  // browsers, and iOS rejects it until notification permission is granted.
  async function apply(nav, count) {
    try {
      if (count > 0 && nav.setAppBadge) await nav.setAppBadge(count);
      else if (nav.clearAppBadge) await nav.clearAppBadge();
    } catch (e) { /* not allowed (yet): the badge is a nicety */ }
  }

  // Whether asking for notification permission could make the badge work.
  function canPrompt(nav, notification) {
    return Boolean(nav.setAppBadge && notification && notification.permission === "default");
  }

  return { dueCount, apply, canPrompt };
});
