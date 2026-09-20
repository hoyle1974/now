---
type: Feature
title: Due time
description: Date-only vs timed due dates and how overdue works.
resource: web/due.js
tags: [due]
timestamp: 2026-09-19T00:00:00Z
---
`due_date` may carry a time. Date-only is stored as midnight and means all-day: overdue once its day ends. Any other time is timed: overdue the moment it passes, shown like "Today 3:00 PM" (`web/due.js`). [Next up](next-up.md) ranks earlier times first within a day, all-day counting as end of day. The icon badge counts open todos due today or overdue (`web/badge.js`; iOS needs notification permission first).
