---
type: Feature
title: Calendar feed (ICS)
description: A private read-only iCalendar feed of open dated todos, subscribed to by URL, plus the More-panel Subscribe / Copy link buttons.
resource: app/ics.py
tags: [calendar, ics, auth, secret]
timestamp: 2026-09-21T23:45:00Z
---
**Feed.** `GET /calendar/<token>.ics` ([routes](../api/routes.md)) returns `text/calendar` built by `app/ics.py` from the live tree ([Todo](../data/todo.md)): one `VEVENT` per todo that is open, not deleted and has a `due_date` (subtasks included, with `DESCRIPTION: Subtask of: <parent>`). A midnight due ([due time](due-time.md)) is an all-day event; a timed due is a 30-minute event in **floating** local time (the user's wall clock, whatever timezone the calendar app is in). Events are `TRANSP:TRANSPARENT` (a todo must not make you look busy), `UID = <todo_id>@now`, `SEQUENCE = version`. A repeating todo is one event: its next occurrence exists only after completion ([repeating](repeating-todos.md)), so there is no `RRULE`. Text is escaped and lines folded at 75 octets without splitting UTF-8. The feed asks clients to refresh hourly; `Cache-Control: private, max-age=300`.

**Auth.** Calendar apps send no headers, so the token is the path. `CALENDAR_TOKEN` (env, from Secret Manager secret `calendar-token`) is compared in constant time in `require_user` (`app/auth.py`); it unlocks **only** `GET /calendar/<token>.ics`. Unset = feed off; any other path or a wrong token falls through to the normal sign-in check (401). Same pattern as the [widget token](../ops/widget.md). Caveat: the token appears in request logs and in every calendar app that subscribes; anyone with the URL can read your due todo titles. Rotate with `scripts/setup-calendar.sh --rotate` (old URL stops at once, re-subscribe).

**Setup.** `scripts/setup-calendar.sh` (or `init.sh --calendar`; idempotent) creates the secret, grants the runtime service account `secretAccessor` on it, sets `CALENDAR_TOKEN` on the service and writes the URL to `.calendar-url` (git-ignored, mode 600; never printed). `doctor.sh` warns when the env is missing.

**In the app.** The More panel has a Calendar row: **Subscribe** (opens `webcal://<host>/calendar/<token>.ics`, which iOS Calendar offers to subscribe to; installed Home Screen apps often ignore `webcal:`, so after 1.5 s it falls back to copying the link for Calendar > Add Subscription) and **Copy link**. The token is never in the page source: the signed-in client calls `GET /calendar/link` (normal auth) which returns `{enabled, path}` (`web/auth.js` must list that path as an API request or no token is sent and the row silently stays dead); the row stays hidden when the feed is off, offline or signed out.

**Multi-user (2026-09-21).** The link route (`app/routes/calendar.py`) checks `auth.calendar_feed_path(tenant.current())` — the feed is one token for the whole family, so `enabled` is only ever true for `auth.owner()` (the first `ALLOWED_EMAILS` entry); every other signed-in user sees `{enabled: false, path: null}`.

**Tests.** `tests/test_calendar.py` (rendering, escaping/folding, the gate, both routes). Verified live: the real link returns 200 `text/calendar`, a wrong token 401. Not verified: an actual subscription in iOS/Google Calendar. Google Calendar polls feeds slowly (hours), whatever the refresh hint says.

**Types.** Only types with `notifies` become events ([item types](item-types.md)).
