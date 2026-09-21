---
type: Feature
title: Push reminders
description: One morning digest of what is due today or overdue, sent once a day as web push through FCM.
resource: app/push.py
tags: [push, notifications, fcm, scheduler]
timestamp: 2026-09-21T03:00:00Z
---
- **Rules** (`plan_device`, pure): one **digest** per device per local day: "3 due today" plus the first three titles, listing every open todo [due today or overdue](due-time.md); a marker-only (silent) tick when nothing is due. The Scheduler decides *when* it runs; the device's timezone only decides which day "today" is, and there is no hour gate, so a manual `scheduler jobs run` at any time sends the day's digest once. There are **no 1-hour heads-ups** (removed 2026-09-21: one tick a day cannot send them).
- **Devices:** the app posts its FCM token, IANA timezone and platform to `POST /push/devices` at each launch (`web/push.js`), so travel just works ([routes](../api/routes.md)). `POST /push/devices/unregister {token}` removes one. Collections `push_devices` and `push_sent` ([Firestore](../data/firestore.md)).
- **Trigger:** Cloud Scheduler job `now-notify` (`*/10 6-23 * * *`, `America/Los_Angeles`) calls `POST /internal/notify` with a Google OIDC token. `require_user` lets that path through only for a token whose audience is env `NOTIFY_AUDIENCE` and whose email is env `NOTIFY_CALLER`; either unset = off, and a Firebase login is rejected there ([auth](../ops/widget.md)).
- **Cost guard:** the run reads only devices and todos due before now+2 days (query `done==false, deleted==false, due_date<cutoff`, composite index in `firestore.indexes.json`), and nothing at all with no device.
- **No duplicates:** the marker (`digest:{local date}:{device}` or `soon:{todo}:{due}:{device}`) is written *before* the send, so a failure loses one push rather than repeating it. Markers expire after 3 days by Firestore TTL on `expires_at`. FCM `UnregisteredError` or `SenderIdMismatchError` deletes the device.
- **Client:** `web/sw.js` shows every push (data-only messages, always displayed, because iOS revokes permission from pushes that show nothing) and focuses the app on tap; it does no caching. The More panel's Reminders button needs a tap for the iOS permission prompt. `web/push.js` uses the Firebase messaging SDK with FCM's default VAPID key (`VAPID_KEY` empty).
- **Setup:** `scripts/setup-push.sh` ([deploy](../ops/deploy.md)). Test a tick with `gcloud scheduler jobs run now-notify --location us-central1`.
