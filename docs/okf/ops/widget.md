---
type: Runbook
title: iOS Lock Screen widget
description: Scriptable widget showing Next up, and its read-only token.
resource: scripts/scriptable-next-up.js
tags: [ios, widget, auth]
timestamp: 2026-09-21T00:30:00Z
---
Widgets can't refresh the hourly Firebase token, so only `GET /todos/next` ([next up](../features/next-up.md)) also accepts `X-Widget-Token` matching env `WIDGET_TOKEN` (`app/auth.py`); unset = off. On Cloud Run the env var is a Secret Manager reference (secret `widget-token`, `latest`; the service account has `secretAccessor` on that secret only). Generate with `openssl rand -hex 24`; rotate with `printf %s <token> | gcloud secrets versions add widget-token --data-file=-` then `gcloud run services update now-app --region us-central1 --update-secrets WIDGET_TOKEN=widget-token:latest` (a new revision is needed to pick up the new version), keep a local copy in `.scriptable-secret` (git-ignored; never commit). Paste `scripts/scriptable-next-up.js` into Scriptable, set `TOKEN` exactly (no trailing chars). Lock Screen rectangular shows top 3; Home small 4, medium 6. "can't load" → check token, `BASE` URL, deployment. iOS controls refresh (~15 min requested).
The [calendar feed](../features/calendar-feed.md) uses the same secret-token pattern for its own route.
