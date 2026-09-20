---
type: Feature
title: Next up
description: Ranking of the top 10 todos to work on.
resource: app/next_up.py
tags: [ranking, api]
timestamp: 2026-09-19T00:00:00Z
---
The second tab. `GET /todos/next` ranks open todos with **no open subtasks** by: (1) the earlier of own due date and nearest due ancestor's, (2) own due date, (3) list order. Top 10. The client only draws the answer; tapping a row jumps to the list with that todo scrolled under the finger. Also feeds the [widget](../ops/widget.md); see [due time](due-time.md).
