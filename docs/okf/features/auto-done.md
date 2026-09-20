---
type: Feature
title: Auto-done parents and done-sink
description: Parent completion rules and display order of done rows.
resource: web/autodone.js
tags: [ui, done]
timestamp: 2026-09-19T00:00:00Z
---
Completing the last open subtask also completes its parent, upward, as ordinary queued edits ([sync](sync-model.md)). One-way: un-doing a subtask or adding one never reopens a parent; checking a parent doesn't change its subtasks; a row shows only its own `done`. Within each group done rows display below open ones (each keeps `order_idx` order); a just-completed row waits for its animation. Display only.
