---
type: Feature
title: Color, links and dependencies
description: color, links, blocked_by, references and the derived blocked flag.
resource: app/models.py
tags: [fields, model]
timestamp: 2026-09-19T20:00:00Z
---
Set via `PATCH /todos/{id}`: lists replace the whole value, `color: null` clears. All are content edits (`If-Match`, version bump) and default to empty on old docs. Colors: red, orange, yellow, green, teal, blue, purple, pink. `links`: ≤20 `{url, label|null}`, http/https. `blocked_by`, `references`: ≤50 todo ids; newly added ids must exist and not be the todo itself (400); an id the todo already holds is kept even after its target was archived; `blocked_by` must stay acyclic (400). Deleted todos' ids are kept (trash is restorable) and ignored when computing `blocked`, which `GET /todos/tree` adds: true if any `blocked_by` todo is live and not done. See [Todo](../data/todo.md).

**Viewer:** tapping a row body opens a full-screen, read-only view of the todo (`renderViewer` in `web/app.js`): title, status, due, repeat, subtask counts, a Blocked note, then the detail panel (links, blocked by, references, [images](attachments.md)). Its Edit button opens the full-screen edit sheet (the same `activePanel` mechanism, mode `"view"`/`"edit"`); a refresh doesn't re-render over the viewer. Replaces the older inline expand-in-place detail panel.
