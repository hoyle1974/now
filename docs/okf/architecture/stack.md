---
type: Architecture
title: Stack
description: Technologies and how the pieces fit together.
tags: [architecture]
timestamp: 2026-09-19T00:00:00Z
---
- **Backend:** FastAPI (`app/main.py`), Python 3.13, pydantic models ([Todo](../data/todo.md)).
- **Database:** Firestore ([collections](../data/firestore.md)). Tests use the emulator ([testing](../ops/testing.md)).
- **Frontend:** vanilla JS in `web/` (no framework, no build step) served with a
  single `index.html`; an offline-first outbox drives all writes
  ([sync model](../features/sync-model.md)).
- **Hosting:** Cloud Run service `now` in `us-central1`, fronted by Firebase Hosting
  at `now-app.web.app` ([deploy](../ops/deploy.md)).
- **Auth:** Firebase sign-in token on API calls (`app/auth.py`, `web/auth.js`);
  a read-only widget token exists for one route ([widget](../ops/widget.md)).
