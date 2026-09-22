---
type: Feature
title: Auto-done parents and done-sink
description: Parent completion rules and display order of done rows.
resource: web/autodone.js, web/confirm-dialog.js
tags: [ui, done]
timestamp: 2026-09-22T16:10:00Z
---
Completing the last open subtask makes its parent *eligible* to complete, upward, but never completes it silently: `app.js`'s `confirmAncestors` asks first, nearest ancestor first, naming the parent ("Mark "<title>" complete?", via `web/confirm-dialog.js`'s Yes/No popup). Saying yes queues that parent's completion as an ordinary queued edit ([sync](sync-model.md)) and, if that now makes the next ancestor up eligible too, asks again for it — so a multi-level cascade is a Yes tap per level. Saying no (or dismissing with Escape/tap-outside) stops the chain for that ancestor and everything above it; nothing is asked again until a later child change makes the same ancestor eligible again (no permanent per-parent suppression). One-way: un-doing a subtask or adding one never reopens a parent; checking a parent doesn't change its subtasks; a row shows only its own `done`. Within each group done rows display below open ones (each keeps `order_idx` order); a just-completed row waits for its animation. Display only (a container's own `done` never styles its row).

**Types.** Containers (`list`/`project`) are passed through and never completed; a todo parent is eligible to complete when every todo beneath it is done ([item types](item-types.md)). `Autodone.ancestorsToComplete` (unit-tested, `tests_js/autodone.test.js`) computes the whole eligible chain up front; `confirmAncestors` just walks it with a confirm popup per step, stopping on the first no. The popup itself is DOM-only, like the attachments lightbox, so it has no `node --test` coverage — verify it in the browser ([local browser testing](../ops/local-browser-testing.md)).
