// Due dates. A date-only due is stored as midnight and treated as all-day; any other
// time of day makes it a timed due. Also the calendar-day helpers (today, tomorrow,
// daysUntil, and "Today" / "Tomorrow" phrasing). No DOM access, so it runs under
// `node --test`.
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

  // ---- calendar days ----------------------------------------------------
  // All take an optional `now` so they can be tested; the app passes nothing.

  const pad = (n) => String(n).padStart(2, "0");
  const dayString = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

  // "YYYY-MM-DD" for today / tomorrow in the device's timezone (what a date input holds).
  function today(now = new Date()) {
    return dayString(now);
  }

  function tomorrow(now = new Date()) {
    const d = new Date(now);
    d.setDate(d.getDate() + 1);
    return dayString(d);
  }

  // Whole calendar days from today to the due date (negative = overdue).
  function daysUntil(iso, now = new Date()) {
    return Math.round((startOfDay(iso) - startOfDay(now)) / 86400000);
  }

  // Relative phrasing for the next week, a short date beyond that: the way native
  // reminders apps talk about time ("Today", "Tomorrow", "Fri").
  function formatDay(iso, now = new Date()) {
    const days = daysUntil(iso, now);
    if (days === 0) return "Today";
    if (days === 1) return "Tomorrow";
    if (days === -1) return "Yesterday";
    if (days < 0) return `${-days} days overdue`;
    const date = new Date(iso);
    if (days < 7) return date.toLocaleDateString(undefined, { weekday: "long" });
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
    });
  }

  // formatDay, plus the time for a timed due ("Today 3:00 PM"); "N days overdue" stays terse.
  function format(iso, now = new Date()) {
    const day = formatDay(iso, now);
    if (!hasTime(iso) || daysUntil(iso, now) < -1) return day;
    return `${day} ${new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
  }

  return { hasTime, timePart, combine, isOverdue, formatRepeat, today, tomorrow, daysUntil, formatDay, format };
});
