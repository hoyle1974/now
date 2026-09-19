// Due date + optional time. A date-only due is stored as midnight and treated
// as all-day; any other time of day makes it a timed due. No DOM access, so it
// runs under `node --test`.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Due = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const TIME = /T(\d{2}):(\d{2})/;

  function hasTime(iso) {
    const m = typeof iso === "string" ? TIME.exec(iso) : null;
    return Boolean(m) && !(m[1] === "00" && m[2] === "00");
  }

  // "HH:MM" for a timed due, "" for all-day or no due (what <input type=time> wants).
  function timePart(iso) {
    const m = hasTime(iso) ? TIME.exec(iso) : null;
    return m ? `${m[1]}:${m[2]}` : "";
  }

  // From a date input and a time input; a time without a date is meaningless.
  function combine(date, time) {
    if (!date) return "";
    return time ? `${date}T${time}:00` : date;
  }

  function startOfDay(d) {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x;
  }

  // All-day dues are overdue once their day has ended; timed dues once the
  // time has passed.
  function isOverdue(iso, now = new Date()) {
    if (!iso) return false;
    if (hasTime(iso)) return new Date(iso) < now;
    return startOfDay(iso) < startOfDay(now);
  }

  // "Daily", "Weekdays", "Every 2 weeks"...
  function formatRepeat(rule) {
    if (!rule) return "";
    const every = rule.every || 1;
    if (rule.unit === "weekday") return "Weekdays";
    if (every === 1) return { day: "Daily", week: "Weekly", month: "Monthly", year: "Yearly" }[rule.unit] || "";
    return `Every ${every} ${rule.unit}s`;
  }

  return { hasTime, timePart, combine, isOverdue, formatRepeat };
});
