---
type: Architecture
title: Stack
description: Technologies and how the pieces fit together.
tags: [architecture]
timestamp: 2026-09-22T00:15:00Z
---
One deployment shared by a family (each person's data isolated), zero GCP cost is the #1 rule ([principles](../principles.md)).

- **Backend:** FastAPI (`app/main.py`, routes in `app/routes/`), Python 3.13, pydantic models ([Todo](../data/todo.md)).
- **Database:** Firestore ([collections](../data/firestore.md)). Tests use the emulator ([testing](../ops/testing.md)).
- **Image storage:** a private Cloud Storage bucket, reached only through the API ([attachments](../features/attachments.md)).
- **Frontend:** vanilla JS in `web/` (no framework, no build step) served with a
  single `index.html`; an offline-first outbox drives all writes
  ([sync model](../features/sync-model.md)).
- **Hosting:** Cloud Run service `now-app` (zilch's `app_name`) in `us-central1`, fronted by Firebase Hosting
  at `now-app.web.app` ([deploy](../ops/deploy.md)).
- **Auth:** Firebase sign-in token on API calls (`app/auth.py`, `web/auth.js`), accepted only for an email in env `ALLOWED_EMAILS` (`;`-separated list, first is the owner; legacy single-value `ALLOWED_EMAIL` still works; required: an empty list denies everyone and the server refuses to start; set on the Cloud Run service). The signed-in email is the data partition key (`app/tenant.py`, [data model](../data/firestore.md), [multi-user](../ops/multi-user.md)) — there is no sharing between the emails on the list;
  a read-only widget token exists for one route ([widget](../ops/widget.md)), and a secret-URL token for the [calendar feed](../features/calendar-feed.md) (owner-only, see that page).
