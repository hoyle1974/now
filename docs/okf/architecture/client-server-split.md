---
type: Architecture
title: Client/server split
description: Which features put their logic in the browser vs the backend, and why — plus the rule for deciding new ones.
tags: [architecture, frontend, backend]
timestamp: 2026-09-22T00:00:00Z
---
The backend is often just CRUD + optimistic concurrency over the [Todo](../data/todo.md) model; a lot of real behaviour is decided entirely client-side, over data the server stores unchanged. This page names which features fall on which side and why, so the split is a decision on record, not an accident of who wrote it first.

**Why this works today:** each user's tree is small and never shared ([multi-user](../ops/multi-user.md) partitions data per email, no cross-user access), so the client can hold and search a whole tenant's data in memory cheaply. That assumption is load-bearing — it's *why* client-only search, auto-done, outline etc. are viable, not just a stylistic choice. If sharing between users is ever added, or a single account's data grows large, several of these stop being free:

- **Search is the one most likely to move.** It's already flagged as a future add: once a user's tree is big enough that fetching-and-filtering everything client-side gets slow (or once trees are ever shared/merged across users), search needs a real server endpoint (indexed query, pagination) rather than an in-memory scan. Revisit `web/search.js` first if this changes.

## Client owns the logic, server is plain CRUD

## Client owns the logic, server is plain CRUD

The server has no route, model field or algorithm backing these — it just stores/returns whatever the client sends. Losing connectivity or replaying from a stale cache doesn't affect correctness because there's no server-side state machine to get out of sync with.

- **Auto-done** ([auto-done](../features/auto-done.md)) — `web/autodone.js` decides which ancestors become done; the server just receives ordinary `PATCH` calls per todo, one at a time.
- **Due-date semantics** ([due time](../features/due-time.md)) — `web/due.js` computes overdue/all-day-vs-timed/today-tomorrow labels from an opaque ISO string; the server never interprets it.
- **Search** — `web/search.js`/`search-ui.js` filters the already-fetched tree in memory (title, links, color, trash); there is no search endpoint.
- **Copy-with-subtasks outline** — `web/outline.js` formats already-fetched tree data into text; no server round-trip at all.
- **Type field rules** ([fields](../features/fields.md)) — the server serves the static type registry once (`types.json` → `web/types-data.js`); which fields show/apply per type is a client-side rule engine (`web/fields.js`/`fields-ui.js`).
- **Offline sync/outbox** ([sync model](../features/sync-model.md)) — `web/sync.js`, `idb-store.js`, `freshness.js`, `remote-diff.js` implement the queue, retry and "what changed" detection entirely client-side, on top of plain CRUD + `if_match` concurrency. The server has no concept of an outbox.
- **Look and feel** (accent theme, completion sound, mascot, sparkle, badge) — `themes.js`, `mascot.js`, `sparkle.js`, `badge.js`. No server model backs any of these; they're local/cosmetic only.
- **Event log** ([event log](../features/event-log.md)) — `web/eventlog.js` is `localStorage` only, on-device diagnostics never sent to the server.
- **Reorder-drop targeting** (partial) — `web/reorder.js` decides which row/gap a drag lands on; the resulting write still goes through a real server transaction (`move_todo`/`reparent_todo`), so this one is split rather than pure client-only.

## Server deliberately owns the logic

These stay server-side on purpose, usually because they need atomicity, cross-device consistency, or to run when no client is open — moving them to the client would break the feature, not just relocate it.

- **Next up ranking** ([next up](../features/next-up.md)) — `app/next_up.py` (effective due date, blocking, list-position tiebreaks) runs server-side so the ranking is identical across every device; `web/next-up-ui.js` only renders what it returns.
- **Repeat/recurrence** ([repeating todos](../features/repeating-todos.md)) — `app/recurrence.py`'s next-occurrence math runs inside the same atomic transaction that creates the next todo (`repeat_todo`); doing this client-side risks duplicate or missing occurrences.
- **Push digest and heads-ups** ([push reminders](../features/push-reminders.md)) — `app/push.py`/`app/tasks.py` must run server-side; they fire on a schedule whether or not a client is open.
- **Calendar feed** ([calendar feed](../features/calendar-feed.md)) — `app/ics.py` is consumed by external calendar apps, not the web UI; there is no client to move it to.
- **Reorder/move persistence** — the final write and ordering guarantee for a reparent/move stays in `app/routes/todos.py` + `db.reorder_todo`, even though the drag targeting above is client-side.

## Rule for new features: discuss the split when it isn't obvious

Before implementing a new feature, decide explicitly where its logic lives:

- **Obvious cases don't need discussion.** Pure presentation/UX (animations, local-only state, formatting) is client-side by default. Anything requiring atomicity, cross-device consistency, or running with no client open (schedules, notifications, multi-user invariants) is server-side by default.
- **When it's not obvious** — e.g. the feature could be computed from data the client already has, but might also need to be consistent across devices, survive offline, or be cheap to keep correct as rules change — **stop and raise it with the user before writing code.** Lay out the client-only option and the server-side option, and what each gives up (offline support vs. consistency, simplicity vs. an extra round-trip, etc.), and let the user pick.
- **Record the decision.** Once decided, add the feature to the right list above (or split it across both, like reorder-drop) in the same commit, per the normal [OKF sync rule](../../../CLAUDE.md).
