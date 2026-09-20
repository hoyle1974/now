# Push reminders design

Status: approved in conversation, pending written-spec review.

## Goal

Notify the user on their installed iOS PWA when todos are due, without waking them at night.

- **Daily digest:** one push at or after 9:00 device-local time if any open todo is due today or overdue.
- **Heads-up:** one push 1 hour before any *timed* todo (not date-only). Before 9:00 local it is held until 9:00, and skipped if the todo is already covered by that day's digest.
- No email. Single user (`ALLOWED_EMAIL`), so no per-user modelling.

Also in scope, because they share the More panel and the client release: tidy the More panel, and stop iOS shake permission needing a manual re-arm after every new version.

## Decisions

- Delivery: Firebase Cloud Messaging web push, sent from Cloud Run with `firebase-admin` (already a dependency). Rejected: plain Web Push with `pywebpush` (we would own VAPID key generation and rotation).
- Trigger: Cloud Scheduler `*/10 6-23 * * *` in `America/Los_Angeles`, `POST /internal/notify`. Cost is trivial (about 3,000 to 4,300 requests a month, one free Scheduler job), provided the handler never scans the whole `todos` collection (see Cost guard).
- Timezone: the device reports its IANA zone (`Intl.DateTimeFormat().resolvedOptions().timeZone`) at every launch. Rejected: a single fixed zone env var (wrong when travelling).
- Heads-up lead: fixed 60 minutes, not configurable per todo.

## Data

- `push_devices/{device_id}`: `token`, `tz`, `platform`, `updated_at`. One doc per installed device. `device_id` is a stable hash of the token, so re-registering upserts.
- `push_sent/{key}`: marker with `expires_at` (Firestore TTL policy deletes it). Keys:
  - `digest:{local_date}:{device_id}`
  - `soon:{todo_id}:{due_iso}:{device_id}`
- One new composite index on `todos` (open, not deleted, by `due_date`) in `firestore.indexes.json`.
- No change to the `Todo` model.

## Server

New module `app/push.py`: pure decision functions plus a thin FCM sender. `app/main.py` gets three routes.

- `POST /push/devices` upserts `{token, tz, platform}`. `DELETE /push/devices` removes the caller's token. Normal Firebase auth.
- `POST /internal/notify`, called only by Scheduler. `require_user` lets this one path through to a separate check that verifies a Google-signed OIDC token: audience equals the service URL, email equals the `now-notify` service account. A Firebase user token, a missing token, a wrong audience or a wrong email is rejected. Nothing else is exempted.

Notify logic, per device, with `now` converted to the device zone:

- **Digest:** if local time is 9:00 or later and no `digest:` marker exists for the local date, count open todos due today or overdue. If greater than zero, send one push ("3 due today", body lists the first few titles). Write the marker either way, so a zero count is not recomputed.
- **Heads-up:** for timed, open todos due within the next 60 minutes with no `soon:` marker, send "Title in 1 hour". Before 9:00 local, hold. If the todo already appeared in that day's digest, skip.
- **Dead tokens:** if FCM reports an unregistered or invalid token, delete the device doc.
- **Ordering:** write the marker together with the send and fail closed. A missed push is preferred over a duplicate.
- Date-only dues are stored as midnight and mean all-day, so they only feed the digest. A due at exactly 00:00 cannot be told from date-only (existing limitation in the due-time doc).

Cost guard: query only the due-date window through the new index, and exit at once when there are no devices, so an idle tick reads about nothing.

## Client

No build step, matching `web/`.

- `web/sw.js` (served at the site root by the existing static route): shows the push notification, and on `notificationclick` focuses the open app window or opens `/`. No caching or offline logic, so it cannot interfere with the outbox sync.
- `web/push.js`: registers the worker, obtains the FCM token with the Firebase messaging SDK and the public VAPID key, and posts `{token, tz, platform}` to `/push/devices`. The SDK loads the same way `web/auth.js` loads the Firebase SDK.
- Permission: iOS needs a user gesture, so the More panel gets a Reminders row (on, off, or blocked with a hint to use iOS Settings). With permission already granted, each launch silently refreshes token and timezone. Every failure is swallowed: push must never break sync. Unsupported browser, denied permission or offline simply leaves it off.
- Push messages carry a `notification` payload plus `data.url` so a tap lands in the app.
- Release: bump `APP_VERSION` in `web/app.js` and the `?v=` in `web/index.html` together, per the existing convention.

## More panel tidy-up

Regroup the wrapped pile of pill buttons into a short vertical settings list in the iOS Settings style:

```
More
  Look       [ accent swatches ]
  Mascot     Sound  ○     Mascot  ●     Shake  ●
  Alerts     Reminders  ●     Icon badge  ○
  Support    Event log ›
```

Markup and CSS only (`web/index.html`, `web/style.css`). Every button keeps its ID, so the existing code that repaints text and `aria-pressed` is untouched, with switch indicators driven by `aria-pressed`. The live shake-strength readout stays.

## Shake permission across versions

Likely cause (unverified, needs a real iPhone): `requestPermission()` needs a tap, `web/mascot.js` only auto-starts listening where no permission is needed, and iOS does not reliably keep the grant across a full relaunch, which a new version usually causes.

Fix: store `shakeEnabled` in `localStorage` when the user turns shake on. On the next launch, re-arm on the first tap anywhere in the app. If iOS still holds the grant this is silent. If it asks again, it asks once on that first tap and never needs the More panel. Log the outcome to the event log so the real iOS behavior can be read afterwards. If the prompt still appears after release, report back and revisit.

## GCP setup (`scripts/setup-push.sh`, idempotent, user reads and runs it)

- Enable the FCM API and grant the Cloud Run service account the minimal FCM send role (verify `roles/firebasemessaging.admin` is the least needed).
- Create service account `now-notify` for Scheduler to mint OIDC tokens. The app verifies the token itself, so no `run.invoker` binding is needed.
- Create Scheduler job `now-notify`: `*/10 6-23 * * *`, `America/Los_Angeles`, OIDC audience equals the service URL.
- Turn on Firestore TTL for `expires_at` on `push_sent`; deploy the index.
- Manual step: generate a Web Push (VAPID) key in the Firebase console and paste the public key into `web/push.js`.

Deploy with `./deploy.sh`, then `say`.

## Testing

- Python pure-function tests: digest and heads-up across timezones, the 9:00 gate, date-only versus timed, heads-up folding into the digest, dedupe markers, DST edges.
- Route tests on the Firestore emulator: device upsert and delete; `/internal/notify` rejects a Firebase token, wrong audience, wrong email and no token, and accepts a valid Scheduler token. FCM sender faked, including a dead-token case that must delete the device.
- `tests_js`: timezone and payload helpers, shake re-arm arms on the first tap only when previously enabled.
- Manual on the phone: enable Reminders, trigger `/internal/notify`, confirm the push arrives and a tap opens the app.

## Docs

New `docs/okf/features/push-reminders.md`; update routes, Firestore collections, deploy and monitoring-backups in the same commit as the code, bump timestamps, add `docs/okf/log.md` lines, and link the new file from `docs/okf/index.md`.

## Order of work

Server and tests, then client and the More tidy-up, then `setup-push.sh`, then deploy.

## Out of scope

Per-todo lead time, snooze and quiet-hours settings, email or SMS, notification actions, and any offline caching in the service worker.
