---
type: Runbook
title: iOS Lock Screen widget
description: Scriptable widget showing Next up, and its read-only token.
resource: scripts/scriptable-next-up.js
tags: [ios, widget, auth]
timestamp: 2026-09-19T00:00:00Z
---
Widgets can't refresh the hourly Firebase token, so only `GET /todos/next` ([next up](../features/next-up.md)) also accepts `X-Widget-Token` matching env `WIDGET_TOKEN` on the Cloud Run service (`app/auth.py`); unset = off. Generate with `openssl rand -hex 24`, set with `gcloud run services update now --region us-central1 --update-env-vars WIDGET_TOKEN=<token>`, keep a local copy in `.scriptable-secret` (git-ignored; never commit). Paste `scripts/scriptable-next-up.js` into Scriptable, set `TOKEN` exactly (no trailing chars). Lock Screen rectangular shows top 3; Home small 4, medium 6. "can't load" → check token, `BASE` URL, deployment. iOS controls refresh (~15 min requested).
