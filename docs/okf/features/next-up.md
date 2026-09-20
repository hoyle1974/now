---
type: Feature
title: Next up
description: Ranking of todos to work on: everything due today or overdue, filled to 10.
resource: app/next_up.py
tags: [ranking, api]
timestamp: 2026-09-20T00:00:00Z
---
The second tab. `GET /todos/next` ranks open todos with **no open subtasks** by: (1) the earlier of own due date and nearest due ancestor's, (2) own due date, (3) list order. The list is 10 long but never cuts off a todo whose effective due date is today or earlier: all of those show, and if fewer than 10, the next most urgent fill it. "Today" is the client's local date, sent as `?today=YYYY-MM-DD`; without it (the widget) the list is a plain top `limit`. The client only draws the answer; tapping a row jumps to the list with that todo scrolled under the finger. Also feeds the [widget](../ops/widget.md); see [due time](due-time.md).
