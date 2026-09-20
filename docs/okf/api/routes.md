---
type: API
title: HTTP routes
description: All routes in app/main.py.
resource: app/main.py
tags: [api]
timestamp: 2026-09-20T12:00:00Z
---
| Route | Purpose |
|---|---|
| `GET /health` | Liveness. |
| `POST /todos` | Create. |
| any route with `X-Txn-Id` | Header must be a safe token (`[A-Za-z0-9_-]{1,100}`, not `__x__`), else 400. |
| `GET /todos/tree` | Full tree; adds derived `blocked`. Triggers the [archive](../features/trash-archive.md) sweep. |
| `GET /todos/rev` | Current revision + app `version`; the cheap freshness check ([sync](../features/sync-model.md)). |
| `GET /todos/next` | [Next up](../features/next-up.md); also accepts `X-Widget-Token` ([widget](../ops/widget.md)). |
| `GET /todos/trash`, `POST /todos/clear-completed`, `PATCH /todos/{id}/undelete` | [Trash](../features/trash-archive.md). |
| `GET /todos/root`, `GET /todos/{id}` | Reads. |
| `PATCH /todos/{id}` | Content edits, `If-Match: <version>`, 409 + current todo on stale ([fields](../features/fields.md)). |
| `PATCH /todos/{id}/reparent` | `{parent_id, index}` move ([ordering](../features/ordering-nesting.md)). |
| `PATCH /todos/{id}/move/{direction}` | Swap with a neighbour. 400 at the top/bottom or with no siblings, 404 if missing; any other failure is a 5xx (the client retries those, it drops 4xx). |
| `POST /todos/{id}/repeat` | Spawn next occurrence ([repeating](../features/repeating-todos.md)). |
| `POST /todos/{id}/split` | Split into several todos. |
| `POST /todos/{id}/attachments` (multipart `file`), `GET`/`DELETE /todos/{id}/attachments/{aid}` | Images on a todo; upload/delete return the updated todo; a `Content-Length` over 10 MB + 1 MB is refused with 413 before the body is read ([attachments](../features/attachments.md)). |
| `POST /push/devices` `{token, tz, platform}`, `POST /push/devices/unregister` `{token}` | Register or drop a device for [push reminders](../features/push-reminders.md); 400 on an unknown timezone. |
| `POST /internal/notify` | Cloud Scheduler only (OIDC); sends due reminders, returns `{devices, sent}`. |
| `DELETE /todos/{id}` | Soft delete (204). |

Writes carry `X-Txn-Id` for idempotency; write responses reveal remote changes via `X-Rev-Prev`.

404 bodies carry a `detail` the client relies on: `todo not found` (the item is gone, drop it locally), `attachment not found`, `parent not found` (reparent target). A bare `Not Found` means the route itself is missing. `DELETE` of a missing todo is an idempotent 204.
