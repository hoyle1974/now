// The one due-date control: chips Today / Tomorrow / Pick date / Clear, plus an optional
// time field. Used by the composer, the new-item sheet and the edit sheet, so a date is
// entered the same way everywhere. The pure helper runs under `node --test`; the DOM part
// needs DOM (dom.js) and Due (due.js) at call time.
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.DatePicker = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Which chip is lit for a "YYYY-MM-DD" (or empty) value. Any other date lights Pick date.
  function chipState(value, today, tomorrow) {
    return {
      today: value === today,
      tomorrow: value === tomorrow,
      custom: Boolean(value) && value !== today && value !== tomorrow,
    };
  }

  // opts: value ("YYYY-MM-DD" or ""), withTime (adds the time field), time ("HH:MM"),
  // rowClass (extra class for the chip row), onChange().
  // Returns { chips, timeField, dateInput, timeInput, date(), time(), value(), set(date) }.
  // Repeat controls listen for "input" on dateInput, so every change fires that event.
  function create(opts = {}) {
    const el = DOM.el;
    const chip = (text, extra) => DOM.button(text, "chip" + (extra ? " " + extra : ""));

    const chips = el("div", "chip-row" + (opts.rowClass ? " " + opts.rowClass : ""));
    const todayChip = chip("Today");
    const tomorrowChip = chip("Tomorrow");
    const pickChip = el("label", "chip chip-pick");
    const pickText = el("span", null, "Pick date");
    const dateInput = el("input");
    dateInput.type = "date";
    dateInput.setAttribute("aria-label", "Pick a due date");
    dateInput.value = (opts.value || "").slice(0, 10);
    pickChip.append(pickText, dateInput);
    const clearChip = chip("Clear", "chip-plain");
    chips.append(todayChip, tomorrowChip, pickChip, clearChip);

    let timeInput = null;
    let timeField = null;
    if (opts.withTime) {
      timeInput = el("input");
      timeInput.type = "time";
      timeInput.value = opts.time || "";
      timeField = el("div", "date-picker-time");
      timeField.append(DOM.label("Time (optional)", timeInput), timeInput);
    }

    const render = () => {
      const state = chipState(dateInput.value, Due.today(), Due.tomorrow());
      todayChip.classList.toggle("is-active", state.today);
      tomorrowChip.classList.toggle("is-active", state.tomorrow);
      pickChip.classList.toggle("is-active", state.custom);
      pickText.textContent = state.custom ? Due.format(`${dateInput.value}T00:00:00`) : "Pick date";
      clearChip.hidden = !dateInput.value;
      if (timeInput) {
        timeInput.disabled = !dateInput.value;
        if (!dateInput.value) timeInput.value = "";
      }
    };
    const change = () => {
      render();
      if (opts.onChange) opts.onChange();
    };
    const setDate = (value) => {
      dateInput.value = value;
      dateInput.dispatchEvent(new Event("input", { bubbles: true }));
    };

    // Tapping the lit Today/Tomorrow chip clears it.
    todayChip.addEventListener("click", () => setDate(dateInput.value === Due.today() ? "" : Due.today()));
    tomorrowChip.addEventListener("click", () =>
      setDate(dateInput.value === Due.tomorrow() ? "" : Due.tomorrow()));
    clearChip.addEventListener("click", () => setDate(""));
    // The date input sits invisibly over its chip; some desktop browsers only open the
    // picker from a small icon, so ask for it explicitly.
    pickChip.addEventListener("click", () => {
      try { dateInput.showPicker(); } catch (e) { /* unsupported: the input still works */ }
    });
    dateInput.addEventListener("input", change);
    render();

    return {
      chips, timeField, dateInput, timeInput,
      date: () => dateInput.value,
      time: () => (timeInput ? timeInput.value : ""),
      value: () => Due.combine(dateInput.value, timeInput ? timeInput.value : ""),
      set: setDate,
    };
  }

  return { chipState, create };
});
