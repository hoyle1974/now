---
type: Feature
title: Repeating todos
description: Repeat rules and server-side spawning of the next occurrence.
resource: app/recurrence.py
tags: [recurrence]
timestamp: 2026-09-19T00:00:00Z
---
`repeat: {unit, every}` (day, weekday = Mon–Fri, week, month, year), set in the edit sheet; needs a due date. Completing queues `POST /todos/{id}/repeat`; in one transaction the server clones the todo and its live subtasks as the next occurrence: open, placed right after the original, next due date stepped from the due date (first after today; month/year clamp to month end; due time kept), dated subtasks shifted equally. The completed original stays as a record. `spawned_id` guarantees at most one spawn even with untick/retick or two devices. Not optimistic: the client reloads the tree on confirmation ([sync](sync-model.md)).
