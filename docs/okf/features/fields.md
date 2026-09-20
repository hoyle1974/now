---
type: Feature
title: Color, links and dependencies
description: color, links, blocked_by, references and the derived blocked flag.
resource: app/models.py
tags: [fields, model]
timestamp: 2026-09-19T00:00:00Z
---
Set via `PATCH /todos/{id}`: lists replace the whole value, `color: null` clears. All are content edits (`If-Match`, version bump) and default to empty on old docs. Colors: red, orange, yellow, green, teal, blue, purple, pink. `links`: ≤20 `{url, label|null}`, http/https. `blocked_by`, `references`: ≤50 todo ids; ids must exist and not be the todo itself (400); `blocked_by` must stay acyclic (400). Deleted todos' ids are kept (trash is restorable) and ignored when computing `blocked`, which `GET /todos/tree` adds: true if any `blocked_by` todo is live and not done. See [Todo](../data/todo.md).
