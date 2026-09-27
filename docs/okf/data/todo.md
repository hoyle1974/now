---
type: Data Model
title: Todo
description: Fields, limits and derived values of a todo document.
resource: app/models.py
tags: [data, model]
timestamp: 2026-09-27T03:00:00Z
---
| Field | Notes |
|---|---|
| `todo_id` | UUID. Client uses a temporary `tmp:` id until the server assigns one ([sync](../features/sync-model.md)). |
| `title`, `done`, `create_date` | Basics. Titles are capped at 2000 chars on write (split: 100 items). `create_date`, `deleted_at`, `last_synced_at` and the trash list's `trashed_at` are naive UTC in storage (`models.utc_now`) but sent as explicit UTC instants (`...Z`); a bare string is read as local time by the browser. `due_date` and `end_date` stay bare (the user's wall-clock time, not an instant). |
| `due_date` | Optional; midnight = all-day ([due time](../features/due-time.md)). |
| `order_idx`, `parent_id`, `child_ids` | Tree position ([ordering](../features/ordering-nesting.md)). |
| `deleted`, `deleted_at` | Soft delete + UTC stamp, sent with `Z` ([trash](../features/trash-archive.md)). |
| `collapsed` | View state; patch skips version bump ([sync](../features/sync-model.md)). |
| `repeat` `{unit: day\|weekday\|week\|month\|year, every: 1–999}`, `spawned_id` | [Repeating](../features/repeating-todos.md). |
| `version` | Bumped on each content write; used with `If-Match`. |
| `color`, `links`, `blocked_by`, `references` | [Fields](../features/fields.md). |
| `attachments` | `[{id, name, content_type, size}]`; bytes are in a bucket, changed only by the attachment routes ([attachments](../features/attachments.md)). |
| `type` | `todo` (default) / `list` / `project` / `note` / `calendar` / `calendar_event` / `mount` (server-managed, never set by a request); missing or unknown reads as `todo`. Changed by `PATCH`, which touches only this field ([item types](../features/item-types.md)). |
| `content` | Note body, Markdown, ≤100,000 characters. `""` or `null` on `PATCH` clears it. Omitted leaves it. Kept when the type changes. A single-child `split` may set it when the child type has the field. |
| `calendar_url`, `last_synced_at`, `last_sync_error` | `calendar` type: the source feed and server-managed sync status ([calendar sync](../features/calendar-sync.md)). `last_synced_at` is sent with `Z`. |
| `external_uid`, `location`, `end_date`, `notes`, `repeat_summary`, `conference_url`, `attendees` | `calendar_event` type, written only by the sync ([calendar sync](../features/calendar-sync.md)). `end_date` is floating wall-clock like `due_date`; `attendees` is `[{name, email, status: accepted\|declined\|tentative\|needs-action, organizer}]` (≤200); `notes` ≤10,000 chars. |
| `priority` | `high` / `normal` / `low`, default `normal`. On `todo` and `calendar_event` only. User-owned: a calendar sync never copies or clears it, and a priority-only patch is allowed on a read-only event (it still bumps `version`). Missing or unknown reads as `normal`. Ranks [Next up](../features/next-up.md). |
| `blocked` | Derived, never stored, only added by `GET /todos/tree`. |
| `last_edited_by` | Email of the last writer; set by the server only on writes inside a share ([sharing](../features/sharing.md)). |
| `share` `{id, mode: ro\|rw, owner}`, `share_root` | Derived, never stored: set by the tree read on every node that comes from a share, and on its root ([sharing](../features/sharing.md)). |

Limits: 20 links, URL ≤2048 chars (http/https), label ≤200, 50 ids per list, 10 attachments of ≤10 MB, note `content` ≤100,000 characters.
