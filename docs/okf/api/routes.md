---
type: API
title: HTTP routes
description: All routes in app/main.py.
resource: app/main.py
tags: [api]
timestamp: 2026-09-19T20:00:00Z
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
| `GET /todos/root`, `GET /todos/print`, `GET /todos/{id}` | Reads. |
| `PATCH /todos/{id}` | Content edits, `If-Match: <version>`, 409 + current todo on stale ([fields](../features/fields.md)). |
| `PATCH /todos/{id}/reparent` | `{parent_id, index}` move ([ordering](../features/ordering-nesting.md)). |
| `PATCH /todos/{id}/parent/{parent_id}`, `PATCH /todos/{id}/move/{direction}` | Older move routes. |
| `POST /todos/{id}/repeat` | Spawn next occurrence ([repeating](../features/repeating-todos.md)). |
| `POST /todos/{id}/split` | Split into several todos. |
| `POST /todos/{id}/attachments` (multipart `file`), `GET`/`DELETE /todos/{id}/attachments/{aid}` | Images on a todo; upload/delete return the updated todo ([attachments](../features/attachments.md)). |
| `DELETE /todos/{id}` | Soft delete (204). |

Writes carry `X-Txn-Id` for idempotency; write responses reveal remote changes via `X-Rev-Prev`.
