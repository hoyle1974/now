---
type: Feature
title: Next up
description: Ranking of todos to work on: everything due today or overdue, filled to 10.
resource: app/next_up.py
tags: [ranking, api]
timestamp: 2026-09-21T07:15:00Z
---
The second tab. `GET /todos/next` ranks open todos with **no open subtasks** by: (1) the earlier of own due date and nearest due ancestor's, (2) own due date, (3) list order. The list is 10 long but never cuts off a todo whose effective due date is today or earlier: all of those show, and if fewer than 10, the next most urgent fill it. "Today" is the client's local date, sent as `?today=YYYY-MM-DD`; without it (the widget) the list is a plain top `limit`. The client only draws the answer; tapping a row jumps to the list with that todo scrolled under the finger. **Blocking:** a todo waits on the open todos in its `blocked_by` (and its ancestors'); after ranking, each blocker is pulled up to sit just above what it blocks, bringing all its open leaves if it has subtasks. Done or deleted blockers don't count ([fields](fields.md)). Also feeds the [widget](../ops/widget.md); see [due time](due-time.md).

A blocked row (`.next-row--blocked`) keeps its rank but its title is dimmed, since it is not actionable yet.

**Types.** Only `appearsInNextUp` types are listed; `list`/`project` are walked through, ignore their own `done` and dormant due date, and are never blockers ([item types](item-types.md)).
