# Push reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a 9am-local digest push and 1-hour-ahead heads-ups for timed todos to the user's installed iOS PWA, plus a tidier More panel and a shake re-arm fix.

**Architecture:** A pure decision module (`app/push.py`) plans notifications per device from open todos and sent-markers. Cloud Scheduler calls `POST /internal/notify` (OIDC-verified) every 10 minutes in daytime; the handler queries todos by due date, writes a marker, then sends through FCM (`firebase-admin`). The client registers a service worker and FCM token and reports its timezone.

**Tech Stack:** FastAPI, Firestore (emulator in tests), firebase-admin messaging, google-auth OIDC, vanilla JS (UMD modules under `node --test`), Cloud Scheduler.

**Spec:** `docs/superpowers/specs/2026-09-19-push-reminders-design.md`

## Global Constraints

- Digest at or after 9:00 device-local (`DIGEST_HOUR = 9`); heads-up lead exactly 60 minutes; digest counts open todos due today or overdue; heads-ups only for timed dues (not midnight/date-only).
- Fail closed: write the sent marker before sending. A missed push beats a duplicate.
- Due dates are naive local wall time (`YYYY-MM-DDTHH:MM:SS`); offset-aware dues are converted to the device zone.
- No whole-collection scans in `/internal/notify`: query by due-date window only.
- Push code must never break sync: client failures are swallowed.
- Tests run only via `scripts/test.sh` (emulator) and `node --test tests_js/*.test.js`.
- Per CLAUDE.md: update `docs/okf/` (with `timestamp` bumps and a `log.md` line) in the same commit as behaviour changes.
- Client release: bump `APP_VERSION` in `web/app.js` and the `?v=` in `web/index.html` together.
- One deviation from the spec: unregister is `POST /push/devices/unregister {token}`, not `DELETE` (a body on DELETE is unreliable and tokens do not belong in URLs).

## File structure

- Create `app/push.py`: pure planner, FCM sender, `run_notify`.
- Modify `app/db_firestore.py`: device, marker and due-window storage.
- Modify `app/auth.py`: scheduler OIDC verification for `/internal/notify`.
- Modify `app/main.py`: three routes.
- Modify `firestore.indexes.json`: composite index.
- Create `web/sw.js`, `web/push.js`; modify `web/auth.js`, `web/index.html`, `web/app.js`, `web/style.css`, `web/mascot.js`.
- Create `scripts/setup-push.sh`; tests `tests/test_push_logic.py`, `tests/test_push_api.py`, `tests_js/push.test.js`, `tests_js/shake.test.js`.

### Task 1: Pure planner (`app/push.py`)

**Files:** Create `app/push.py`, `tests/test_push_logic.py`

**Interfaces:**
- Produces: `Push(key, title, body, todo_ids, silent)`, `plan_device(dev_id, tz, now_utc, todos, sent) -> list[Push]` where `sent(key) -> list[str] | None`, `device_id(token) -> str`, `valid_tz(name) -> bool`.

- [ ] **Step 1: Write failing tests** in `tests/test_push_logic.py` covering: before 9:00 local nothing; digest at 9:00 lists due-today and overdue with count title; digest marker-only (`silent`) when nothing due; no second digest when marker exists; timed todo due in 45 min gets a heads-up, in 90 min does not; date-only never gets a heads-up; heads-up window opened before 9:00 and todo in digest ids is skipped; a 3pm todo already in the 9am digest still gets its 2pm heads-up; timezone respected (same UTC instant is 09:00 in Los_Angeles but 12:00 in New_York).
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_push_logic.py -q` fails (no module).
- [ ] **Step 3: Implement** `app/push.py`:

```python
"""Push reminders: decide what to send (pure) and send it (thin)."""
from __future__ import annotations
import datetime
import hashlib
from dataclasses import dataclass
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from app import models

DIGEST_HOUR = 9
LEAD = datetime.timedelta(hours=1)
MAX_TITLES = 3


@dataclass(frozen=True)
class Push:
    key: str
    title: str
    body: str
    todo_ids: tuple[str, ...] = ()
    silent: bool = False  # marker only, nothing is sent


def device_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:32]


def valid_tz(name: object) -> bool:
    try:
        ZoneInfo(str(name))
        return bool(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name) if valid_tz(name) else ZoneInfo("UTC")


def _local_due(todo: models.Todo, zone: ZoneInfo) -> datetime.datetime | None:
    due = todo.due_date
    if due is None:
        return None
    return due.astimezone(zone).replace(tzinfo=None) if due.tzinfo else due


def _is_timed(due: datetime.datetime) -> bool:
    return due.time() != datetime.time(0, 0)


def plan_device(dev_id: str, tz: str, now_utc: datetime.datetime,
                todos: list[models.Todo], sent: Callable[[str], list[str] | None]) -> list[Push]:
    zone = _zone(tz)
    now = now_utc.astimezone(zone).replace(tzinfo=None)
    if now.hour < DIGEST_HOUR:
        return []
    today = now.date()
    nine = datetime.datetime.combine(today, datetime.time(DIGEST_HOUR))
    open_ = [(t, _local_due(t, zone)) for t in todos if not t.done and not t.deleted and t.due_date]
    out: list[Push] = []

    dkey = f"digest:{today.isoformat()}:{dev_id}"
    prior = sent(dkey)
    digest_ids = set(prior or [])
    if prior is None:
        due = sorted(((d, t) for t, d in open_ if d.date() <= today), key=lambda p: p[0])
        ids = tuple(str(t.todo_id) for _, t in due)
        n = len(due)
        titles = ", ".join(t.title for _, t in due[:MAX_TITLES])
        if n > MAX_TITLES:
            titles += f" +{n - MAX_TITLES} more"
        out.append(Push(dkey, f"{n} due today", titles, ids, silent=(n == 0)))
        digest_ids = set(ids)

    for t, d in open_:
        if not _is_timed(d) or not datetime.timedelta(0) < d - now <= LEAD:
            continue
        key = f"soon:{t.todo_id}:{t.due_date.isoformat()}:{dev_id}"
        if sent(key) is not None:
            continue
        if d - LEAD < nine and str(t.todo_id) in digest_ids:
            continue  # its window opened overnight: the digest already covers it
        out.append(Push(key, t.title, f"Due at {d.strftime('%-I:%M %p')}, in about an hour"))
    return out
```
- [ ] **Step 4:** run the tests; expect PASS.
- [ ] **Step 5: Commit** `feat: pure push planner`.

### Task 2: Storage and index

**Files:** Modify `app/db_firestore.py` (append), `firestore.indexes.json`; Test `tests/test_push_api.py` (storage part)

**Interfaces:**
- Produces in `app.db`: `upsert_push_device(dev_id, token, tz, platform)`, `delete_push_device(dev_id)`, `list_push_devices() -> list[dict]` (each has `id`, `token`, `tz`, `platform`), `get_push_marker(key) -> list[str] | None`, `put_push_marker(key, todo_ids, expires_at)`, `get_due_todos(before: datetime) -> list[models.Todo]` (open, not deleted, `due_date` string `<` `before.isoformat()`).

- [ ] **Step 1: Failing tests:** upsert twice keeps one device; delete removes; marker round trip returns ids and unset returns `None`; `get_due_todos` returns only open, non-deleted todos due before the cutoff (create four todos to prove each exclusion).
- [ ] **Step 2:** run, expect FAIL (`AttributeError`).
- [ ] **Step 3: Implement** with `get_conn().collection("push_devices")`, `"push_sent"` (field `expires_at` datetime for TTL), and `get_conn().collection("todos").where("done","==",False).where("deleted","==",False).where("due_date","<",before.isoformat())`, mapped through `db_firestore_helpers.doc_to_todo`. Add to `firestore.indexes.json` a `todos` composite index: `done ASC, deleted ASC, due_date ASC`.
- [ ] **Step 4:** run, expect PASS.
- [ ] **Step 5: Commit** `feat: push device, marker and due-window storage`.

### Task 3: Auth, notify runner and routes

**Files:** Modify `app/push.py` (append), `app/auth.py`, `app/main.py`; Test `tests/test_push_api.py`

**Interfaces:**
- Consumes: Task 1 and 2 signatures.
- Produces: `class DeadToken(Exception)`, `send_fcm(token, push)`, `run_notify(now_utc, send=send_fcm) -> {"devices": int, "sent": int}`; routes `POST /push/devices`, `POST /push/devices/unregister`, `POST /internal/notify`; `auth.verify_scheduler(request)`.

- [ ] **Step 1: Failing tests:** `POST /push/devices` stores and upserts, rejects an invalid tz (400) and an empty token (422); unregister removes; `run_notify` with a fake sender sends the digest once and not again on a second run (marker), writes the marker even when the send raises, deletes the device on `DeadToken`, does nothing with no devices; `require_user` on `/internal/notify` (call it directly with a built `starlette.requests.Request`) rejects no header, a bad token, wrong audience, wrong email; accepts a valid one (monkeypatch `auth._verify_oidc`); other paths are unaffected.
- [ ] **Step 2:** run, expect FAIL.
- [ ] **Step 3: Implement.** `run_notify`: list devices; return early if none; `todos = db.get_due_todos((now_utc + timedelta(days=2)).replace(tzinfo=None))`; for each device, for each `Push` from `plan_device(..., db.get_push_marker)`: `db.put_push_marker(p.key, list(p.todo_ids), now_utc + timedelta(days=3))` first, skip when silent, then `send(dev["token"], p)`; on `DeadToken` delete the device and stop that device; on any other exception `logging.exception` and continue. `send_fcm` sends a data-only `messaging.Message(token, data={"title","body","url":"/"}, webpush=WebpushConfig(headers={"Urgency":"high","TTL":"3600"}))` and maps `UnregisteredError` and `SenderIdMismatchError` to `DeadToken`. In `auth.py` add `_SCHEDULER_PATHS = {"/internal/notify"}`, `_verify_oidc(token, audience)` using `google.oauth2.id_token.verify_oauth2_token` with `google.auth.transport.requests.Request()`, and `verify_scheduler(request)` reading env `NOTIFY_AUDIENCE` and `NOTIFY_CALLER` at call time (either unset means 403); `require_user` calls it for those paths and returns. Register the routes in `main.py` before the static mount.
- [ ] **Step 4:** run the full suite with `scripts/test.sh`; expect PASS.
- [ ] **Step 5: Commit** `feat: /internal/notify, device routes, scheduler auth`.

### Task 4: Client, More panel and shake fix

**Files:** Create `web/sw.js`, `web/push.js`, `tests_js/push.test.js`, `tests_js/shake.test.js`; Modify `web/auth.js` (add `messagingSenderId: "<project-number>"`, and make sure its fetch wrapper also covers `/push` requests), `web/index.html`, `web/app.js`, `web/style.css`, `web/mascot.js`

**Interfaces:**
- Produces: `Push.status(env)` returns `"unsupported" | "blocked" | "off" | "on"`; `Push.registerBody(token, tz, platform)`; `Push.parse(eventJson)` returns `{title, body, url}` (used by `sw.js` logic; duplicated inline there); `Mascot.armOnFirstTap(doc, storage, request)`.

- [ ] **Step 1: Failing JS tests:** `status` matrix; `registerBody` shape; `parse` handles `{data:{...}}`, a bare object and garbage (falls back to a generic title); `armOnFirstTap` does nothing without the stored flag, registers one `pointerup` listener with it, calls `request` once on the first tap and never again.
- [ ] **Step 2:** `node --test tests_js/push.test.js tests_js/shake.test.js`, expect FAIL.
- [ ] **Step 3: Implement** `web/push.js` (UMD helpers plus `enable()`/`refresh()` using `firebase.messaging().getToken({serviceWorkerRegistration})`, adding `vapidKey` only when a constant is set, then `POST /push/devices {token,tz,platform}`; every failure caught), `web/sw.js` (push handler that always shows a notification, `notificationclick` focusing or opening `/`), `firebase-messaging-compat.js` script tag (10.14.1, same as the app and auth scripts), the More panel regrouped into Look, Mascot, Alerts and Support rows keeping every existing button ID, a Reminders button (`id="push-toggle"`) wired in `app.js` with a silent `Push.refresh()` at launch when permission is already granted, `mascot.js` storing `now.shakeOn` and re-arming on the first tap (and dispatching a `shake-armed` event that `app.js` uses to repaint the button, logging the outcome with `logEvent`), and bump `APP_VERSION` and every `?v=`.
- [ ] **Step 4:** run all JS tests with `node --test tests_js/*.test.js`; expect PASS.
- [ ] **Step 5: Commit** `feat: client push registration, tidy More panel, shake re-arm`.

### Task 5: GCP setup, docs, deploy, phone test

**Files:** Create `scripts/setup-push.sh`, `docs/okf/features/push-reminders.md`; Modify `docs/okf/index.md`, `api/routes.md`, `data/firestore.md`, `ops/deploy.md`, `ops/monitoring-backups.md`, `log.md`

- [ ] **Step 1:** write `scripts/setup-push.sh` (idempotent): enable `fcm.googleapis.com`, `fcmregistrations.googleapis.com`, `firebaseinstallations.googleapis.com`, `cloudscheduler.googleapis.com`; grant the Cloud Run service account `roles/firebasecloudmessaging.admin`; create service account `now-notify`; set `NOTIFY_AUDIENCE` and `NOTIFY_CALLER` on the service; create or update Scheduler job `now-notify` (`*/10 6-23 * * *`, `America/Los_Angeles`, OIDC with that account and audience); set the Firestore TTL on `push_sent.expires_at`.
- [ ] **Step 2:** OKF docs and log line, then commit.
- [ ] **Step 3:** deploy the index (`firebase deploy --only firestore:indexes`), run the setup script (user reads and runs it), `./deploy.sh`, then `say`.
- [ ] **Step 4:** on the phone: More, Reminders, allow. Trigger one notify run (`gcloud scheduler jobs run now-notify`) and confirm the push arrives and a tap opens the app.

## Self-review

- Spec coverage: digest and heads-up rules (Task 1), data model and index (2), routes and scheduler auth (3), service worker, permission flow, tidy panel and shake fix (4), GCP setup, testing and docs (5). Out-of-scope items are not planned.
- Type consistency: `Push`, `plan_device`, `run_notify` and the `db` function names are used identically across tasks.
