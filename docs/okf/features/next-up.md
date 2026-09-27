---
type: Feature
title: Next up
description: Ranking of todos to work on: everything due today or overdue, filled to 10, plus calendar events.
resource: app/next_up.py
tags: [ranking, api]
timestamp: 2026-09-27T06:00:00Z
---
The second tab. `GET /todos/next` ranks open todos with **no open subtasks** by: (1) the earlier of own due date and nearest due ancestor's, (2) own due date, (3) list order. The list is 10 long but never cuts off a todo whose effective due date is today or earlier: all of those show, and if fewer than 10, the next most urgent fill it. "Today" is the client's local date, sent as `?today=YYYY-MM-DD`; without it the list is a plain top `limit`. The client only draws the answer; tapping a row jumps to the list with that todo scrolled under the finger. **Blocking:** a todo waits on the open todos in its `blocked_by` (and its ancestors'); after ranking, each blocker is pulled up to sit just above what it blocks, bringing all its open leaves if it has subtasks. Done or deleted blockers don't count ([fields](fields.md)); see [due time](due-time.md).

**Calendar events** ([calendar sync](calendar-sync.md)) do not consume the 10. The limit is filled from everything else first. Events due today or earlier are then always added, even past 10. If the combined list is still shorter than 10, the nearest later events fill the remaining slots. Each event is slotted into the list by the same due-date order, so a meeting still sits with the work due around it. Without `today`, events only fill slots the other items left empty. That rule is the **normal** pass.

**Priority** (`high` / `normal` / `low`, default `normal`) is on `todo` and `calendar_event` only ([item types](item-types.md)). It is applied after the ranking above, still server-side. Every high item is included and placed first, even when it is not due yet, including a calendar event that would otherwise wait for a free slot; highs sort by due date among themselves and do not push a normal item due today off the list. Normal items keep the rules above, including calendar events not counting toward the 10. Low items are left out of that pass. If the combined high + normal list is still shorter than 10, the soonest lows fill the remaining slots. A low item due today, event or todo, is not forced in. A blocker stays directly above what it blocks when they share a priority; when they differ, it sits with the highest-priority item it blocks and is not duplicated.

A blocked row (`.next-row--blocked`) keeps its rank but its title is dimmed, since it is not actionable yet.

**Types.** Only `appearsInNextUp` types are listed; `list`/`project`/`note`/`calendar` are walked through, ignore their own `done` and dormant due date, and are never blockers ([item types](item-types.md)). `calendar_event` is listed, but outside the limit, as above.

Shared items ([sharing](sharing.md)) are ranked like your own: `GET /todos/next` ranks your tree with every share you have in your list spliced in, so each member sees a shared item that's due.
