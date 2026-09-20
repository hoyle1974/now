---
type: Feature
title: Due time
description: Date-only vs timed due dates and how overdue works.
resource: web/due.js
tags: [due]
timestamp: 2026-09-19T15:00:00Z
---
`due_date` may carry a time. Date-only is stored as midnight and means all-day: overdue once its day ends. Any other time is timed: overdue the moment it passes, shown like "Today 3:00 PM" (`web/due.js`). [Next up](next-up.md) ranks earlier times first within a day, all-day counting as end of day. Limitation: a due at exactly 00:00 is always treated as all-day, so a todo deliberately timed at midnight can't be told apart (by design; date-only is stored as midnight). Offset-aware dues are compared as UTC. The icon badge counts open todos due today or overdue (`web/badge.js`; iOS needs notification permission first).

**Picking a date in the edit sheet:** the chip row is Today / Tomorrow / Clear. An empty date field is blank on iOS, so the text "Pick a date" is shown over it while it is empty (tapping the native input opens the picker; the hint ignores pointer events). An earlier "Pick date" chip using `showPicker()` did nothing on iOS and was removed.
