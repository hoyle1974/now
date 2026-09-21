---
type: API
title: HTTP routes
description: Routes live in app/routes/*.py, mounted by app/main.py.
resource: app/routes
tags: [api]
timestamp: 2026-09-21T14:00:00Z
---
| Route | Purpose |
|---|---|
| `GET /health` | Liveness. |
| `POST /todos` | Create; optional `type` ([item types](../features/item-types.md)). |
| `GET /todos/tree` | Full tree; adds derived `blocked`. Triggers the [archive](../features/trash-archive.md) sweep. |
| `GET /todos/rev` | Current revision + app `version`; the cheap freshness check ([sync](../features/sync-model.md)). |
| `GET /todos/next` | [Next up](../features/next-up.md); also accepts `X-Widget-Token` ([widget](../ops/widget.md)). |
| `GET /todos/trash`, `POST /todos/clear-completed`, `PATCH /todos/{id}/undelete` | [Trash](../features/trash-archive.md). |
| `GET /todos/root`, `GET /todos/{id}` | Reads. |
| `PATCH /todos/{id}` | Content edits, `If-Match: <version>`, 409 + current todo on stale ([fields](../features/fields.md)). |
| `PATCH /todos/{id}/reparent` | `{parent_id, index}` move ([ordering](../features/ordering-nesting.md)). |
| `PATCH /todos/{id}/move/{direction}` | Swap with a neighbour. 400 at the top/bottom or with no siblings, 404 if missing; any other failure is a 5xx (the client retries those, it drops 4xx). |
| `POST /todos/{id}/repeat` | Spawn next occurrence ([repeating](../features/repeating-todos.md)). |
| `POST /todos/{id}/split` | Add several children; optional `type` for all of them. |
| `POST /todos/{id}/attachments` (multipart `file`), `GET`/`DELETE /todos/{id}/attachments/{aid}` | Images on a todo; upload/delete return the updated todo; a `Content-Length` over 10 MB + 1 MB is refused with 413 before the body is read ([attachments](../features/attachments.md)). |
| `GET /calendar/<token>.ics` | [Calendar feed](../features/calendar-feed.md): read-only ICS; the secret path token is the auth (no sign-in header), only this route. |
| `GET /calendar/link` | Signed-in: `{enabled, path}` for the More panel's Subscribe / Copy link. |
| `POST /push/devices` `{token, tz, platform}`, `POST /push/devices/unregister` `{token}` | Register or drop a device for [push reminders](../features/push-reminders.md); 400 on an unknown timezone. |
| `POST /internal/notify` | Cloud Scheduler only (OIDC), once a day; sends the digest and makes heads-up tasks, returns `{devices, sent, scheduled}`. |
| `POST /internal/notify-todo` `{todo_id, due}` | Cloud Tasks only (same OIDC check); sends one 1-hour heads-up unless the todo changed, returns `{sent}` ([push reminders](../features/push-reminders.md)). |
| `DELETE /todos/{id}` | Soft delete (204). |

Writes carry `X-Txn-Id` for idempotency (a safe token, `[A-Za-z0-9_-]{1,100}` and not `__x__`, else 400 on any route); write responses reveal remote changes via `X-Rev-Prev`.

404 bodies carry a `detail` the client relies on: `todo not found` (the item is gone, drop it locally), `attachment not found`, `parent not found` (reparent target). A bare `Not Found` means the route itself is missing. `DELETE` of a missing todo is an idempotent 204.

`PATCH /todos/{id}` also accepts `type` (`todo`/`list`/`project`, else 422); it changes only the type ([item types](../features/item-types.md)).
