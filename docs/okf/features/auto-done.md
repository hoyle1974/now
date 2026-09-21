---
type: Feature
title: Auto-done parents and done-sink
description: Parent completion rules and display order of done rows.
resource: web/autodone.js
tags: [ui, done]
timestamp: 2026-09-21T08:30:00Z
---
Completing the last open subtask also completes its parent, upward, as ordinary queued edits ([sync](sync-model.md)). One-way: un-doing a subtask or adding one never reopens a parent; checking a parent doesn't change its subtasks; a row shows only its own `done`. Within each group done rows display below open ones (each keeps `order_idx` order); a just-completed row waits for its animation. Display only (a container's own `done` never styles its row).

**Types.** Containers (`list`/`project`) are passed through and never completed; a todo parent completes when every todo beneath it is done ([item types](item-types.md)).
