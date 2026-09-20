---
type: Data Model
title: Todo
description: Fields, limits and derived values of a todo document.
resource: app/models.py
tags: [data, model]
timestamp: 2026-09-19T12:00:00Z
---
| Field | Notes |
|---|---|
| `todo_id` | UUID. Client uses a temporary `tmp:` id until the server assigns one ([sync](../features/sync-model.md)). |
| `title`, `done`, `create_date` | Basics. |
| `due_date` | Optional; midnight = all-day ([due time](../features/due-time.md)). |
| `order_idx`, `parent_id`, `child_ids` | Tree position ([ordering](../features/ordering-nesting.md)). |
| `deleted`, `deleted_at` | Soft delete + UTC stamp ([trash](../features/trash-archive.md)). |
| `collapsed` | View state; patch skips version bump ([sync](../features/sync-model.md)). |
| `repeat` `{unit: day\|weekday\|week\|month\|year, every: 1–999}`, `spawned_id` | [Repeating](../features/repeating-todos.md). |
| `version` | Bumped on each content write; used with `If-Match`. |
| `color`, `links`, `blocked_by`, `references` | [Fields](../features/fields.md). |
| `attachments` | `[{id, name, content_type, size}]`; bytes are in a bucket, changed only by the attachment routes ([attachments](../features/attachments.md)). |
| `blocked` | Derived, never stored, only added by `GET /todos/tree`. |

Limits: 20 links, URL ≤2048 chars (http/https), label ≤200, 50 ids per list, 10 attachments of ≤10 MB.
