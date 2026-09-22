---
type: Runbook
title: Local server and Chrome testing
description: How to run the app locally against the Firestore emulator and drive it in Chrome, signed in as one or two test users.
tags: [tests, local, chrome, multi-user]
timestamp: 2026-09-22T21:00:00Z
---
Unit tests do not cover `web/app.js` and the other top-level UI scripts, so any UI change needs a look in a real browser before it ships. A refactor once deleted the engine setup from `app.js`; every test still passed and only the browser showed a blank app. Do this before deploying UI changes. Never point it at production: it uses the emulator and a copy of `web/`.

**Why a scratch copy.** The real `web/config.js` carries the Firebase web config, so `auth.js` shows the sign-in overlay and wraps `fetch` with an ID token nothing can mint. The copy gets a stub `config.js` (`window.NOW_CONFIG = {};`, which makes `auth.js` bail out) and the server runs with the sign-in dependency overridden, exactly as `tests_js/e2e_server.py` does (outside `app/`, so it never ships). The override must still set `request.state.user` itself (not just return `None`) — since the multi-user partition, every data route needs a tenant bound (`app/tenant.py`) or it 500s with "no user bound".

**Single test user** (most UI changes need only this):

```bash
S=<scratch dir>                                   # anything outside the repo
rm -rf $S/web && cp -R web $S/web && echo 'window.NOW_CONFIG={};' > $S/web/config.js
cat > $S/serve.py <<EOF2
import os, sys
sys.path.insert(0, "<repo>")
os.environ.setdefault("ALLOWED_EMAILS", "e2e@example.com")
import app.main as m
from app.auth import require_user
from fastapi import Request
from fastapi.staticfiles import StaticFiles
app = m.app
def _fake_user(request: Request) -> None:
    request.state.user = "e2e@example.com"
app.dependency_overrides[require_user] = _fake_user
app.router.routes = [r for r in app.router.routes if getattr(r, "name", "") != "web"]   # drop the real static mount
app.mount("/", StaticFiles(directory="$S/web", html=True), name="web2")
EOF2
firebase emulators:exec --only firestore --project demo-now-test \
  "GOOGLE_CLOUD_PROJECT=demo-now-test PYTHONPATH=<repo> .venv/bin/uvicorn serve:app --app-dir $S --port 8082 & sleep 600"
curl -s localhost:8082/health                      # {"status":"ok"} once it is up
```
`emulators:exec` shuts the emulator down when its command ends, so the `sleep` keeps it alive; stop early with `pkill -f "uvicorn serve:app"; pkill -f emulators:exec`. Re-copy `web/` after every edit (the server serves the copy). The emulator starts empty each time.

**Two test users (multi-user isolation check).** The server has no real sign-in to distinguish browser profiles, so run **two server instances against the same emulator**, each hard-wired to a different allowed email, on two ports; point one browser profile/incognito window at each port (a device shared between two people is out of scope — this is testing two people, each on their own "device"/port):

```bash
S=<scratch dir>
rm -rf $S/web && cp -R web $S/web && echo 'window.NOW_CONFIG={};' > $S/web/config.js
for PORT_USER in 8082:owner@example.com 8083:kid@example.com; do
  PORT=${PORT_USER%%:*}; USER=${PORT_USER#*:}
  cat > $S/serve-$PORT.py <<EOF2
import sys
sys.path.insert(0, "<repo>")
import os
os.environ.setdefault("ALLOWED_EMAILS", "owner@example.com;kid@example.com")
import app.main as m
from app.auth import require_user
from fastapi import Request
from fastapi.staticfiles import StaticFiles
app = m.app
def _fake_user(request: Request) -> None:
    request.state.user = "$USER"
app.dependency_overrides[require_user] = _fake_user
app.router.routes = [r for r in app.router.routes if getattr(r, "name", "") != "web"]
app.mount("/", StaticFiles(directory="$S/web", html=True), name="web2")
EOF2
done
firebase emulators:exec --only firestore --project demo-now-test \
  "GOOGLE_CLOUD_PROJECT=demo-now-test PYTHONPATH=<repo> .venv/bin/uvicorn serve-8082:app --app-dir $S --port 8082 & \
   GOOGLE_CLOUD_PROJECT=demo-now-test PYTHONPATH=<repo> .venv/bin/uvicorn serve-8083:app --app-dir $S --port 8083 & \
   sleep 600"
curl -s localhost:8082/health; curl -s localhost:8083/health
```
Open `http://localhost:8082/` (owner) in one Chrome profile/window and `http://localhost:8083/` (kid) in a separate profile or incognito window — not the same tab or profile, so cookies/localStorage don't bleed between them. Both talk to the same Firestore emulator, partitioned by the email each port hard-codes, which is exactly what proves isolation: create/edit on 8082 must never show up on 8083 and vice versa, and the More panel's calendar row must be visible only on 8082 (the owner, first `ALLOWED_EMAILS` entry).

**Driving it in Chrome** (the Claude in Chrome tools):
1. Open `http://localhost:8082/` in a new tab.
2. Hide the sign-in overlay once per page load: `document.getElementById("signin").hidden = true`.
3. Script the UI from the page. App state lives in top-level `const`s, reachable by name from `javascript_exec`: `model` (`model.roots`, `model.todosById`), `engine`, `toast`, `showNotice`, `apiFetch`. Drive real controls (`.todo-kebab`, `.todo-menu-item`, `#add-title` + `#add-form`.requestSubmit(), `.sheet .type-chip`, `#error .toast-action`) rather than calling internals, wait ~300-600 ms after each action for the sync round trip, and assert on `model` and the DOM.
4. `read_console_messages` with `onlyErrors: true` shows uncaught exceptions; reload first so console tracking sees page load. If `model` or `engine` is `undefined`, a top-level script threw during load: read the first error.
5. Screenshot at the default size; use `resize_window` (e.g. 390x844) for phone width.
6. Close the tab when done.

**Pre-deploy UI checklist.** For any UI change, walk [the UI feature inventory](../features/ui-inventory.md) for everything the change could touch, at minimum: create an item from the composer; open a row's viewer (Images section present); open Edit from the `...` menu and from the viewer (Images section present, type, dates, color, links); change type and Undo; delete and Undo; open Trash and a trashed item; search for a trashed item. A feature that was on the list before and is not reachable now is a regression even if every test passes.

**Calendar checklist** (any change touching [calendar sync](../features/calendar-sync.md) or [item types](../features/item-types.md)' `allowsUserChildren`/`editable` flags):
- Create an item, set its type to **Calendar** (Type panel or the composer/new-item type picker), then Edit it and set `calendar_url` to a real, reachable `.ics` URL (a public Google Calendar secret address works). Save.
- Open the calendar item's row menu `...`: confirm **Add item** and **Add several** are both absent (a `calendar` has `allowsUserChildren: false`); confirm dragging another row onto it does not offer it as a drop target.
- Open the calendar item's **viewer**: confirm a last-synced status line (or a sync error) and a **Sync now** button are present. Tap **Sync now**; it should not block or show a spinner (the request is fire-and-forget). Reload the tree (pull to refresh, or a fresh `GET /todos/tree`) after a few seconds and confirm `calendar_event` children now appear under the calendar (may need the emulator's Cloud Tasks path stubbed/dispatched — if Cloud Tasks isn't wired up locally, confirm at least that the button POSTs `/todos/{id}/sync` with `read_network_requests` and returns 202, since the async sync itself needs a real queue).
- Open a synced `calendar_event` row (once present): confirm **no checkbox**, tapping the row opens a **read-only viewer** with no Edit button, and its row menu `...` has **no** Edit, Type, Move up/down or Delete entries — only Copy with subtasks. Confirm it cannot be dragged to reorder.
- Confirm a `calendar_event` with a due date shows up in **Next up** like an ordinary todo (`appearsInNextUp: true`), and if push/digest is testable locally, that it would be included in the digest (`notifies: true`) — code-review-only is acceptable here if the local emulator has no push devices registered.
- This checklist has not been run against a real browser as part of Task 11 of the calendar-type plan (documentation-only pass, no browser tool available in that environment) — run it before deploying the calendar feature.

**Multi-user isolation checklist** (any change touching auth, tenant partitioning, push, or the calendar/budget owner-only paths — [multi-user runbook](multi-user.md)): using the two-port setup above,
- as the owner (8082): the full checklist above passes (add/edit/complete/reorder/trash/undelete/search, More panel incl. calendar link, attachments);
- as the second user (8083): the list starts empty; none of the owner's todos appear; adding/editing a todo there never appears back on 8082; the More panel has **no** calendar row at all.

**Pitfalls.**
- **The service worker caches `?v=` scripts cache-first.** After changing a file without bumping the version, the browser keeps serving the old one (this hid a fix once). Clear it: `for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister(); for (const k of await caches.keys()) await caches.delete(k); location.reload()`. Bumping `APP_VERSION` and the `?v=` numbers in `index.html` (they must match) also works.
- Sign-in is stubbed, so the real auth path (token refresh, 401 handling) is not exercised; nor are Cloud Tasks, push or attachments' bucket (`ATTACHMENTS_BUCKET` unset).
- Dates are the browser's local day; the emulator has no seed data, so create what you need through the composer.
- Deploy only after the local run and `scripts/test.sh`, `node --test tests_js/*.test.js` and `scripts/e2e.sh` pass ([testing](testing.md), [deploy](deploy.md)).
