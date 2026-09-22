# Per-user data partition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `now` deployment serves several family members, each seeing only their own data (todos, archive, trash, push devices, attachments, revision counter, idempotency log).

**Architecture:** The signed-in email (already verified against an allowlist) is the partition key. Every Firestore path lives under `users/{email}/…` and every blob key under `users/{email}/…`. The email travels in a `ContextVar` (`app/tenant.py`) set by an async FastAPI dependency (so it reaches sync routes in the threadpool) and by `tenant.as_user()` around background/scheduler work. Any data access without a bound user raises (fail closed). No sharing between users.

**Tech Stack:** FastAPI, Firestore (emulator for tests), Cloud Storage, Cloud Tasks, vanilla JS client.

**Spec:** none. Decisions are recorded here (see Global Constraints) and came from the design conversation of 2026-09-21.

## Global Constraints

- Partition key is the **lower-cased email**, not the Firebase uid. Reason: the allowlist is email-based, the widget/calendar/scheduler paths have no token to read a uid from, and the migration needs no user lookup.
- **No sharing** between users. No shared lists, no cross-user reads.
- Access is a fixed env allowlist: `ALLOWED_EMAILS` (separators `;` `,` or whitespace; `;` is what `deploy.sh` must use because gcloud splits `--set-env-vars` on commas). Legacy `ALLOWED_EMAIL` is still read when `ALLOWED_EMAILS` is unset. The **first** entry is the **owner**.
- Widget token, calendar token, budget alerts and the migrated legacy data belong to the **owner** only.
- Fail closed: a data call with no bound user raises `RuntimeError` (a 500), never falls back to a default user.
- Existing data is **migrated** into `users/{owner}/…` by a script (back up first). No fresh start.
- **Cost (#1 rule):** no new Scheduler job, no min instances, no always-on CPU. The 9:00 digest still runs as one job and loops over users. Reads scale with the number of users (one tree read per todo, per user, only when their `rev` moves); say this loudly in the OKF and the final report.
- `docs/okf/principles.md` currently says multi-tenancy is a non-goal. The user asked for this feature; update that principle in the same commit (Task 6).
- Never drop a user-facing feature (project `CLAUDE.md`). Run the UI checklist in `docs/okf/ops/local-browser-testing.md` in Chrome before deploying.
- Tests run only via `scripts/test.sh` (Firestore emulator). JS: `tests_js/`.

## File Structure

- Create `app/tenant.py` — the current-user ContextVar (`set_user`, `reset`, `current`, `as_user`).
- Modify `app/auth.py` — allowlist, `owner()`, `request.state.user`, `bind_user`, per-user `calendar_feed_path`.
- Modify `app/db_firestore.py` — `user_ref`, `_todos`, `_sub`; replace every global collection; per-user caches; `prune_txn_log` loops users.
- Modify `app/db.py` — export `user_ref`.
- Modify `app/blobstore.py` — per-user keys/prefixes.
- Modify `app/main.py` — add `bind_user` dependency.
- Modify `app/routes/calendar.py`, `app/routes/notifications.py`, `app/push.py` (`HeadsUp.user`), `app/tasks.py` (task body carries the user).
- Create `scripts/migrate-to-users.py` — one-off copy of old top-level data and blobs.
- Create `tests/helpers.py`; modify the tests that clear collections (list in Task 2).
- Modify `deploy.sh`, `run.sh`, `.now.env.example`, `scripts/doctor.sh`, `scripts/init.sh`, `README.md`, `docs/okf/*`.

Out of scope by explicit request: client changes for a device shared by two family members (previous-person's-outbox, stale push token). Each person is expected to use their own device.

---

### Task 1: Tenant context and multi-email auth

**Files:**
- Create: `app/tenant.py`, `tests/test_tenant.py`
- Modify: `app/auth.py`, `app/main.py:35`, `tests/test_auth.py:76`, `conftest.py:15`, `tests_js/e2e_server.py:12`

**Interfaces:**
- Produces: `tenant.set_user(email: str) -> Token`, `tenant.reset(token) -> None`, `tenant.current() -> str` (raises `RuntimeError` if unbound), `tenant.as_user(email)` context manager; `auth.ALLOWED_EMAILS: tuple[str, ...]`, `auth.owner() -> str`, `auth.bind_user(request) -> None` (async dependency), `auth.calendar_feed_path(user: str) -> str | None`; `require_user` sets `request.state.user` (lower-case email) for every authorised user/token request and leaves it unset for `/health` and the scheduler paths.

- [ ] **Step 1: Write the failing tests**

`tests/test_tenant.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import auth, tenant


def test_current_raises_when_unbound():
    with pytest.raises(RuntimeError):
        tenant.current()


def test_as_user_binds_lowercases_and_restores():
    with tenant.as_user(" Kid@Example.com "):
        assert tenant.current() == "kid@example.com"
    with pytest.raises(RuntimeError):
        tenant.current()


def _req(path="/todos/root", authorization=None, widget=None, method="GET"):
    headers = [(b"authorization", authorization.encode())] if authorization else []
    if widget:
        headers.append((b"x-widget-token", widget.encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""})


def _two_users(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ("me@example.com", "kid@example.com"))
    monkeypatch.setattr(auth.firebase_admin, "_apps", {"x": 1})
    monkeypatch.setattr(auth.fb_auth, "verify_id_token",
                        lambda t: {"email": f"{t}@example.com", "email_verified": True})


def test_every_allowed_email_passes_and_is_recorded(monkeypatch):
    _two_users(monkeypatch)
    for who in ("me", "kid"):
        r = _req(authorization=f"Bearer {who}")
        auth.require_user(r)
        assert r.state.user == f"{who}@example.com"


def test_email_not_on_the_list_is_403(monkeypatch):
    _two_users(monkeypatch)
    with pytest.raises(auth.HTTPException) as e:
        auth.require_user(_req(authorization="Bearer stranger"))
    assert e.value.status_code == 403


def test_widget_token_acts_as_owner(monkeypatch):
    _two_users(monkeypatch)
    monkeypatch.setattr(auth, "WIDGET_TOKEN", "s3cret")
    r = _req("/todos/next", widget="s3cret")
    auth.require_user(r)
    assert r.state.user == "me@example.com"


def test_calendar_feed_path_is_owner_only(monkeypatch):
    _two_users(monkeypatch)
    monkeypatch.setattr(auth, "CALENDAR_TOKEN", "a" * 20)
    assert auth.calendar_feed_path("me@example.com") == f"/calendar/{'a' * 20}.ics"
    assert auth.calendar_feed_path("kid@example.com") is None


def test_legacy_single_email_env_is_still_read():
    assert auth._parse_emails("Me@Example.com") == ("me@example.com",)
    assert auth._parse_emails("a@x.com; b@x.com,c@x.com  a@x.com") == ("a@x.com", "b@x.com", "c@x.com")


def test_bound_user_reaches_a_sync_route_in_the_threadpool(monkeypatch):
    """The risk this plan rests on: a ContextVar set by the async dependency must be
    visible inside a sync route function (which FastAPI runs in a worker thread)."""
    _two_users(monkeypatch)
    mini = FastAPI(dependencies=[Depends(auth.require_user), Depends(auth.bind_user)])

    @mini.get("/whoami")
    def whoami() -> dict:
        return {"user": tenant.current()}

    c = TestClient(mini)
    assert c.get("/whoami", headers={"Authorization": "Bearer kid"}).json() == {"user": "kid@example.com"}
    assert c.get("/whoami", headers={"Authorization": "Bearer me"}).json() == {"user": "me@example.com"}
```

- [ ] **Step 2: Run to verify failure**

Run: `scripts/test.sh tests/test_tenant.py`
Expected: FAIL (`ImportError: cannot import name 'tenant'`).

- [ ] **Step 3: Implement**

`app/tenant.py`:

```python
"""Whose data the current request works on.

Set once per request by app.auth.bind_user, or around background work with as_user().
Every Firestore path and blob key is derived from current(); with nobody bound it
raises, so a forgotten binding fails loudly instead of touching the wrong account."""
from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_user", default=None)


def set_user(email: str) -> contextvars.Token:
    return _current.set(email.strip().lower())


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> str:
    email = _current.get()
    if not email:
        raise RuntimeError("no user bound: data access outside a request or tenant.as_user()")
    return email


@contextlib.contextmanager
def as_user(email: str) -> Iterator[None]:
    token = set_user(email)
    try:
        yield
    finally:
        reset(token)
```

`app/auth.py` — replace the header/`ALLOWED_EMAIL`/`check_config` block (lines 1-20) with:

```python
"""Family gate: every API request must carry a Firebase ID token for an email in
ALLOWED_EMAILS (legacy: ALLOWED_EMAIL). The email is the data partition key
(app/tenant.py). Static files stay public (they hold no data)."""
from __future__ import annotations

import hmac
import os
import re

import firebase_admin
from fastapi import HTTPException, Request
from firebase_admin import auth as fb_auth

from app import tenant


def _parse_emails(raw: str) -> tuple[str, ...]:
    """Split on ; , or whitespace ( ';' because gcloud splits env vars on commas), lower-case, de-duplicate."""
    return tuple(dict.fromkeys(e.strip().lower() for e in re.split(r"[;,\s]+", raw) if e.strip()))


# The Google accounts allowed in. No default: an empty list denies everyone
# (require_user) and stops the server at startup (check_config).
ALLOWED_EMAILS = _parse_emails(os.environ.get("ALLOWED_EMAILS") or os.environ.get("ALLOWED_EMAIL", ""))


def owner() -> str:
    """The first allowed email. The widget token, calendar feed and budget alerts are theirs."""
    return ALLOWED_EMAILS[0] if ALLOWED_EMAILS else ""


def check_config() -> None:
    if not ALLOWED_EMAILS:
        raise RuntimeError("ALLOWED_EMAILS is not set: export the Google accounts that may sign in, "
                           "first one is the owner (deploy: ALLOWED_EMAILS='you@example.com;kid@example.com' ./deploy.sh)")
```

Replace `calendar_feed_path` with:

```python
def calendar_feed_path(user: str) -> str | None:
    """The secret feed path for that signed-in user to show, or None when the feed is off
    or the user is not the owner (the token is the owner's)."""
    if user != owner() or not CALENDAR_TOKEN or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", CALENDAR_TOKEN):
        return None
    return f"/calendar/{CALENDAR_TOKEN}.ics"
```

Replace `require_user` (and add `bind_user` after it):

```python
def require_user(request: Request) -> None:
    if request.url.path in _PUBLIC_PATHS:
        return
    if request.url.path in _SCHEDULER_PATHS:
        verify_scheduler(request)  # no user: the handlers bind one with tenant.as_user
        return
    if _widget_token_ok(request) or _calendar_token_ok(request):
        request.state.user = owner()
        return
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    try:
        claims = fb_auth.verify_id_token(header[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid or expired token") from None
    email = (claims.get("email") or "").lower()
    if not claims.get("email_verified") or email not in ALLOWED_EMAILS:
        raise HTTPException(403, "Not allowed")
    request.state.user = email


async def bind_user(request: Request) -> None:
    """Runs after require_user. Async on purpose: it executes in the request's own task,
    so the ContextVar it sets is copied into the worker thread that runs a sync route."""
    email = getattr(request.state, "user", None)
    if email:
        tenant.set_user(email)
```

`app/main.py:35` becomes:

```python
app = FastAPI(lifespan=lifespan, dependencies=[Depends(require_user), Depends(bind_user), Depends(check_txn_id)])
```

and extend the import there (`from app.auth import bind_user, require_user`, matching the existing import line).

`tests/test_auth.py:76`: `monkeypatch.setattr(auth, "ALLOWED_EMAIL", "")` → `monkeypatch.setattr(auth, "ALLOWED_EMAILS", ())`. `conftest.py:15`: `os.environ["ALLOWED_EMAILS"] = "me@example.com;other@example.com"`. `tests_js/e2e_server.py:12`: `os.environ.setdefault("ALLOWED_EMAILS", "e2e@example.com")`.

- [ ] **Step 4: Run to verify pass**

Run: `scripts/test.sh tests/test_tenant.py tests/test_auth.py`
Expected: PASS. If `test_bound_user_reaches_a_sync_route_in_the_threadpool` fails, **stop**: the whole design depends on it; switch the routes to read `request.state.user` explicitly instead and re-plan.

- [ ] **Step 5: Commit**

```bash
git add app/tenant.py app/auth.py app/main.py tests/test_tenant.py tests/test_auth.py conftest.py tests_js/e2e_server.py
git commit -m "Auth: allow several emails, bind the signed-in email as the current user"
```

---

### Task 2: Partition Firestore and blobs by user

**Files:**
- Modify: `app/db_firestore.py`, `app/db.py`, `app/blobstore.py`
- Create: `tests/helpers.py`, `tests/test_tenant_isolation.py`
- Modify (test plumbing, mechanical): `tests/test_main.py`, `test_trash.py`, `test_item_types.py`, `test_fields_api.py`, `test_next_up.py`, `test_push_api.py`, `test_review_backend.py`, `test_calendar.py`, `test_tasks.py`, `test_txn_id.py`, `test_attachments.py`, `test_db_firestore_init.py`

**Interfaces:**
- Consumes: `tenant.current()`, `tenant.as_user`, `tenant.set_user`, `tenant.reset` (Task 1).
- Produces: `db.user_ref(email: str | None = None)` → Firestore `DocumentReference` of `users/{email}` (defaults to the bound user); `blobstore.key_for(todo_id, attachment_id)` and `blobstore.todo_prefix(todo_id)` now include `users/{current}/`; new `blobstore.user_todos_prefix() -> str` = `f"users/{tenant.current()}/todos/"`; `tests/helpers.py`: `TEST_USER`, `OTHER_USER`, `wipe_users()`, `act_as(app, email=TEST_USER)`.

Collection layout after this task (all under `users/{email}/`): `todos`, `todos_archive`, `txn_log`, `meta` (docs `rev`, `archive`), `push_devices`, `push_sent`.

- [ ] **Step 1: Write the failing isolation tests and the test helpers**

`tests/helpers.py`:

```python
from app import auth, db, tenant

TEST_USER = "me@example.com"
OTHER_USER = "other@example.com"


def wipe_users() -> None:
    """Empty the emulator's per-user data (needs db.init() first)."""
    client = db.get_conn()
    # users/{email} parent docs never exist (only their subcollections), which is exactly
    # what list_documents() returns; delete each subcollection through it.
    for user in client.collection("users").list_documents():
        for sub in user.collections():
            for doc in sub.stream():
                doc.reference.delete()


def act_as(app, email: str = TEST_USER) -> None:
    """Skip real sign-in in TestClient tests and bind `email` as the request's user."""
    async def _bind() -> None:
        tenant.set_user(email)
    app.dependency_overrides[auth.require_user] = lambda: None
    app.dependency_overrides[auth.bind_user] = _bind
```

`tests/test_tenant_isolation.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app import blobstore, db, tenant
from app.main import app
from tests.helpers import OTHER_USER, TEST_USER, act_as, wipe_users

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup():
    db.init()
    wipe_users()
    blobstore.use_memory()
    yield
    app.dependency_overrides.clear()
    db.teardown()


def test_one_users_todos_are_invisible_to_another():
    act_as(app, TEST_USER)
    made = client.post("/todos", json={"title": "mine"}).json()
    act_as(app, OTHER_USER)
    assert "mine" not in client.get("/todos/root").text
    assert client.get(f"/todos/{made['todo_id']}").status_code == 404
    act_as(app, TEST_USER)
    assert "mine" in client.get("/todos/root").text


def test_each_user_has_their_own_revision_counter():
    act_as(app, TEST_USER)
    client.post("/todos", json={"title": "a"})
    client.post("/todos", json={"title": "b"})
    rev_me = client.get("/todos/rev").json()
    act_as(app, OTHER_USER)
    assert client.get("/todos/rev").json() != rev_me


def test_a_txn_id_is_not_replayed_across_users():
    act_as(app, TEST_USER)
    first = client.post("/todos", json={"title": "mine"}, headers={"X-Txn-Id": "same-id"}).json()
    act_as(app, OTHER_USER)
    second = client.post("/todos", json={"title": "theirs"}, headers={"X-Txn-Id": "same-id"}).json()
    assert second["title"] == "theirs"
    assert second["todo_id"] != first["todo_id"]


def test_an_unbound_data_call_raises_instead_of_picking_a_user():
    with pytest.raises(RuntimeError):
        db.get_rev()


def test_documents_live_under_users_email():
    with tenant.as_user(TEST_USER):
        client_ = TestClient(app)
        act_as(app, TEST_USER)
        made = client_.post("/todos", json={"title": "x"}).json()
    ref = db.user_ref(TEST_USER).collection("todos").document(made["todo_id"])
    assert ref.get().exists
    assert not db.get_conn().collection("todos").document(made["todo_id"]).get().exists


def test_blob_keys_are_per_user():
    with tenant.as_user(TEST_USER):
        a = blobstore.key_for("t1", "a1")
    with tenant.as_user(OTHER_USER):
        b = blobstore.key_for("t1", "a1")
    assert a == "users/me@example.com/todos/t1/a1"
    assert b == "users/other@example.com/todos/t1/a1"


def test_prune_txn_log_covers_every_user():
    import datetime
    old = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)
    for email in (TEST_USER, OTHER_USER):
        db.user_ref(email).collection("txn_log").document("old").set({"created_at": old})
    assert db.prune_txn_log() == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `scripts/test.sh tests/test_tenant_isolation.py`
Expected: FAIL (`AttributeError: module 'app.db' has no attribute 'user_ref'`).

- [ ] **Step 3: Implement `db_firestore.py`**

3a. `_State` (top of file) loses `todos` and gets per-user caches:

```python
class _State:
    """Per-process Firestore state. init() fills it, teardown() clears it."""
    def __init__(self) -> None:
        self.client: Any = None
        # user email -> (rev, roots, todosById) of that user's last full tree read. A tree
        # read costs one document read per todo, so it is reused for as long as the
        # revision counter hasn't moved (every write to a todo bumps it in run_atomic).
        self.tree_cache: dict[str, tuple] = {}
        # user email -> time.monotonic() of that user's last archive attempt
        self.archive_checked: dict[str, float] = {}

    def reset(self) -> None:
        self.tree_cache = {}
        self.archive_checked = {}
```

3b. Add the accessors right after `_state = _State()` (add `from app import tenant` to the existing `from app import …` line):

```python
USERS = "users"


def user_ref(email: str | None = None):
    """users/{email}: every collection below belongs to that one person. Defaults to
    the bound user (app/tenant.py) and raises when none is bound."""
    return get_conn().collection(USERS).document(email or tenant.current())


def _todos():
    return user_ref().collection("todos")


def _sub(name: str):
    return user_ref().collection(name)
```

3c. `init()` / `teardown()`: delete the `_state.todos = …` lines (both).

3d. Mechanical replacements (run, then fix what the compiler/ruff flags):

```bash
sed -i '' 's/_state\.todos/_todos()/g' app/db_firestore.py
sed -i '' 's/get_conn()\.collection(TXN_COLLECTION)/_sub(TXN_COLLECTION)/; s/get_conn()\.collection(REV_COLLECTION)/_sub(REV_COLLECTION)/; s/client\.collection(TXN_COLLECTION)/_sub(TXN_COLLECTION)/; s/client\.collection(REV_COLLECTION)/_sub(REV_COLLECTION)/; s/client\.collection(ARCHIVE_COLLECTION)/_sub(ARCHIVE_COLLECTION)/; s/get_conn()\.collection(PUSH_DEVICES)/_sub(PUSH_DEVICES)/g; s/get_conn()\.collection(PUSH_SENT)/_sub(PUSH_SENT)/g; s/get_conn()\.collection("todos")/_todos()/' app/db_firestore.py
grep -n "get_conn()\.collection\|client\.collection\|_state\.todos" app/db_firestore.py
```

Expected: the last grep prints nothing except `user_ref` itself and `prune_txn_log` (next step). `_todos()` in `db_firestore_helpers.get_subtree_docs(_todos(), …)` is fine (it takes a collection).

3e. `get_tree`: key the cache by user.

```python
    user = tenant.current()
    if rev is None:
        rev = get_rev()
    cached = _state.tree_cache.get(user)
    if cached is not None and cached[0] == rev:
        return copy.deepcopy(cached[1:])
    roots, reachable = _read_tree()
    _state.tree_cache[user] = (rev, roots, reachable)
    return copy.deepcopy((roots, reachable))
```

3f. `maybe_archive_expired`: replace the three `_state.archive_checked` uses with `_state.archive_checked.get(user)` / `_state.archive_checked[user] = …` where `user = tenant.current()` is read at the top. The `_archive_lock` stays process-wide (one sweep at a time is still right).

3g. `sweep_orphan_blobs`: list the user's prefix and parse relative to it:

```python
    prefix = blobstore.user_todos_prefix()
    for key, created in store.list_blobs(prefix):
        parts = key[len(prefix):].split("/")
        if len(parts) != 2 or _aware(created) > cutoff:
            continue
        todo_id, attachment_id = parts
```

(the rest of the loop is unchanged; `_todos().document(todo_id)` already replaced by 3d).

3h. `prune_txn_log`: it runs at startup with no user, so loop the users:

```python
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)
    removed = 0
    for user in get_conn().collection(USERS).list_documents():  # includes users with no user doc, only subcollections
        for doc in user.collection(TXN_COLLECTION).where("created_at", "<", cutoff).stream():
            doc.reference.delete()
            removed += 1
    return removed
```

3i. `app/db.py`: add `user_ref` to the import list and to `__all__`.

3j. `app/blobstore.py`: add `from app import tenant`, update the module docstring line to `Keys look like users/{email}/todos/{todo_id}/{attachment_id}`, and replace the two key helpers:

```python
def user_todos_prefix() -> str:
    return f"users/{tenant.current()}/todos/"


def key_for(todo_id: str, attachment_id: str) -> str:
    return f"{user_todos_prefix()}{todo_id}/{attachment_id}"


def todo_prefix(todo_id: str) -> str:
    return f"{user_todos_prefix()}{todo_id}/"
```

- [ ] **Step 4: Migrate the existing tests' plumbing**

Every test file that clears collections has a fixture like:

```python
db.init()
for name in ("todos", "txn_log", "meta", ...):
    for doc in db.get_conn().collection(name).stream():
        doc.reference.delete()
```

Replace that loop with `wipe_users()` and bind the default user for direct `db.*` calls in the test thread:

```python
from app import tenant
from tests.helpers import TEST_USER, act_as, wipe_users

@pytest.fixture
def db_setup():
    db.init()
    wipe_users()
    token = tenant.set_user(TEST_USER)
    yield 0
    tenant.reset(token)
    db.teardown()
```

Keep each file's own fixture name/shape (`setup`, `db_setup`, `client`). In files that did `app.dependency_overrides[require_user] = lambda: None` (`test_trash.py:12`, `test_item_types.py:14`, `test_calendar.py` fixture), replace with `act_as(app)` (or `act_as(app, TEST_USER)`). Direct collection pokes change from the global collection to the user's:

| Was | Now |
|---|---|
| `db.get_conn().collection("todos")` (`test_review_backend.py:39`, `test_tasks.py:200`) | `db.user_ref(TEST_USER).collection("todos")` |
| `db.get_conn().collection("todos_archive")` (`test_review_backend.py:146`) | `db.user_ref(TEST_USER).collection("todos_archive")` |
| `db.get_conn().collection("meta")` (`test_review_backend.py:159`) | `db.user_ref(TEST_USER).collection("meta")` |
| `db.get_conn().collection("txn_log")` (`test_txn_id.py:39`) | `db.user_ref(TEST_USER).collection("txn_log")` |

`test_db_firestore_init.py:14`: delete `mock_client.collection.assert_called_once_with("todos")` (and any assertion on `_state.todos`): `init()` no longer touches a collection.

- [ ] **Step 5: Run the whole Python suite**

Run: `scripts/test.sh`
Expected: PASS, including `tests/test_tenant_isolation.py`. Fix stragglers with `grep -rn "collection(\"todos\|_state.todos\|collection(name)" tests app`.

- [ ] **Step 6: Commit**

```bash
git add app tests
git commit -m "Data: partition todos, archive, txn_log, rev, push and blobs by user email"
```

---

### Task 3: Routes, push and heads-ups per user

**Files:**
- Modify: `app/routes/calendar.py`, `app/routes/notifications.py`, `app/push.py:26-30`, `app/tasks.py` (`create_task`), `app/routes/common.py` (none needed; verify)
- Test: `tests/test_calendar.py`, `tests/test_push_api.py`, `tests/test_tasks.py`

**Interfaces:**
- Consumes: `auth.owner()`, `auth.ALLOWED_EMAILS`, `auth.calendar_feed_path(user)`, `tenant.as_user`, `tenant.current`.
- Produces: `push.HeadsUp.user: str | None` (absent on tasks queued before this change → owner); Cloud Task JSON body `{"todo_id", "due", "user"}`; `/internal/notify` returns the same keys as before (`devices`, `sent`, `scheduled`), summed over users.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_calendar.py` (use its existing `client` fixture and `TOKEN` constant; it monkeypatches `auth.CALENDAR_TOKEN` already, follow that pattern):

```python
def test_calendar_link_is_hidden_from_non_owners(client, monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ("me@example.com", "kid@example.com"))
    act_as(app, "me@example.com")
    assert client.get("/calendar/link").json()["enabled"] is True
    act_as(app, "kid@example.com")
    assert client.get("/calendar/link").json() == {"enabled": False, "path": None}
```

Append to `tests/test_push_api.py` (its autouse `setup` fixture already inits the db; the app override there uses `require_user` no-op, switch it to `act_as`):

```python
def test_digest_runs_for_every_user_and_never_crosses(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ("me@example.com", "kid@example.com"))
    sent = []
    for email in ("me@example.com", "kid@example.com"):
        with tenant.as_user(email):
            db.upsert_push_device(f"dev-{email}", f"tok-{email}", "America/Los_Angeles", "ios")
            db.create_todo(models.Todo(title=f"due for {email}", due_date=dt.datetime(2026, 9, 19, 9, 0)))
    from app.routes import notifications
    monkeypatch.setattr(push, "send_fcm", lambda token, p: sent.append((token, p.body)))
    out = notifications.notify()
    assert out["devices"] == 2
    tokens = {t for t, _ in sent}
    assert tokens == {"tok-me@example.com", "tok-kid@example.com"}
    for token, body in sent:
        assert token.split("tok-")[1] in body  # each device only hears about its own owner's todo


def test_heads_up_binds_the_user_named_in_the_task(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", ("me@example.com", "kid@example.com"))
    from app.routes import notifications
    seen = []
    monkeypatch.setattr(push, "run_heads_up", lambda todo_id, due, now, send=None: seen.append(tenant.current()) or {"sent": 0})
    notifications.notify_todo(push.HeadsUp(todo_id="x", due="y", user="kid@example.com"))
    notifications.notify_todo(push.HeadsUp(todo_id="x", due="y"))  # task queued before this change
    assert seen == ["kid@example.com", "me@example.com"]
    with pytest.raises(HTTPException):
        notifications.notify_todo(push.HeadsUp(todo_id="x", due="y", user="stranger@example.com"))
```

Append to `tests/test_tasks.py`:

```python
def test_task_body_names_the_user(monkeypatch):
    captured = {}
    class FakeClient:
        def create_task(self, request, timeout=None):
            captured["body"] = json.loads(request["task"].http_request.body)
    monkeypatch.setattr(tasks, "_client", FakeClient())
    monkeypatch.setenv("REMINDER_QUEUE", "projects/p/locations/l/queues/q")
    monkeypatch.setenv("NOTIFY_AUDIENCE", "https://x.example")
    monkeypatch.setenv("NOTIFY_CALLER", "sa@x.iam")
    with tenant.as_user("kid@example.com"):
        assert tasks.create_task("tid", "2026-09-21T10:00:00", dt.datetime.now(dt.UTC)) is True
    assert captured["body"] == {"todo_id": "tid", "due": "2026-09-21T10:00:00", "user": "kid@example.com"}
```

(add the imports these need: `json`, `tenant`, `auth`, `HTTPException`, `push`, `models`, `act_as`, `app` as each file already does for its neighbours.)

Also add to `tests/test_tenant.py` (both background paths swallow exceptions, `_housekeeping` in `app/routes/todos.py:36-40` and `tasks.schedule_from_body`, so a lost binding would otherwise pass every test silently):

```python
def test_background_tasks_see_the_bound_user(monkeypatch):
    _two_users(monkeypatch)
    from fastapi import BackgroundTasks
    seen = []
    mini = FastAPI(dependencies=[Depends(auth.require_user), Depends(auth.bind_user)])

    @mini.get("/bg")
    def bg(background: BackgroundTasks) -> dict:
        background.add_task(lambda: seen.append(tenant.current()))
        return {}

    TestClient(mini).get("/bg", headers={"Authorization": "Bearer kid"})
    assert seen == ["kid@example.com"]
```

- [ ] **Step 2: Run to verify failure**

Run: `scripts/test.sh tests/test_calendar.py tests/test_push_api.py tests/test_tasks.py tests/test_tenant.py`
Expected: FAIL (link still enabled for the kid; `HeadsUp` has no `user`; task body has no `user`).

- [ ] **Step 3: Implement**

`app/routes/calendar.py`: `calendar_link(request: Request)` uses the bound user:

```python
from app import auth, db, ics, tenant

@router.get("/calendar/link")
def calendar_link() -> dict:
    """For the More panel (signed in): where the calendar feed lives, or enabled=false
    (also for anyone but the owner: the feed token is the owner's)."""
    path = auth.calendar_feed_path(tenant.current())
    return {"enabled": path is not None, "path": path}
```

`app/push.py` `HeadsUp`:

```python
class HeadsUp(BaseModel):
    """Body of a Cloud Tasks delivery (app/tasks.py): the todo and the due time the task was
    made for, and whose todo it is (absent on tasks queued before users existed: the owner)."""
    todo_id: str = Field(min_length=1, max_length=64)
    due: str = Field(min_length=1, max_length=64)
    user: str | None = Field(None, max_length=320)
```

`app/tasks.py` `create_task`: `body=json.dumps({"todo_id": todo_id, "due": due_iso, "user": tenant.current()}).encode()`; add `tenant` to `from app import push, tenant, types`.

`app/routes/notifications.py`:

```python
from fastapi import APIRouter, HTTPException

from app import auth, db, push, tenant

@router.post("/internal/notify")
def notify() -> dict:
    """Cloud Scheduler tick (OIDC-verified in require_user): send each allowed user's due
    reminders. One job serves everyone; the totals keep the old response shape."""
    now = datetime.datetime.now(datetime.UTC)
    total = {"devices": 0, "sent": 0, "scheduled": 0}
    for email in auth.ALLOWED_EMAILS:
        try:
            with tenant.as_user(email):
                out = push.run_notify(now, send=push.send_fcm)
        except Exception:
            logging.exception("digest failed for one user; the others still get theirs")
            continue
        for key in total:
            total[key] += out.get(key, 0)
    return total

@router.post("/internal/budget-alert")
def budget_alert(body: push.PubSubEnvelope) -> dict:
    """... tell the owner's devices immediately (billing is the owner's business)."""
    with tenant.as_user(auth.owner()):
        return push.run_budget_alert(body.message.data, datetime.datetime.now(datetime.UTC), send=push.send_fcm)

@router.post("/internal/notify-todo")
def notify_todo(body: push.HeadsUp) -> dict:
    """Cloud Tasks delivery for one heads-up (OIDC-verified in require_user)."""
    user = (body.user or auth.owner()).lower()
    if user not in auth.ALLOWED_EMAILS:
        raise HTTPException(400, "unknown user")
    with tenant.as_user(user):
        return push.run_heads_up(body.todo_id, body.due, datetime.datetime.now(datetime.UTC), send=push.send_fcm)
```

(add `import logging`.) The device/register routes (`register_push_device`, `unregister_push_device`) need no change: they run under the bound user.

Also check: `tasks.schedule_from_body` runs as a `BackgroundTasks` job after the response; the ContextVar set by `bind_user` is still in that context. Confirm with the isolation suite plus `tests/test_tasks.py`.

- [ ] **Step 4: Run to verify pass**

Run: `scripts/test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app tests
git commit -m "Per-user digests, heads-ups and calendar link; owner-only tokens and budget alerts"
```

---

### Task 4: Migration script (existing data → owner)

**Files:**
- Create: `scripts/migrate-to-users.py`, `tests/test_migrate_to_users.py`

**Interfaces:**
- Consumes: `blobstore.get_store()` (`list_blobs`, `get`, `put`), the Firestore client, `db.user_ref`.
- Produces: `migrate(client, store, owner, dry_run, only_missing=False) -> dict` counting copied docs and blobs; CLI `python scripts/migrate-to-users.py OWNER_EMAIL [--apply] [--only-missing]` (dry run by default). Idempotent (a re-run overwrites from the old data), never deletes the old data. `--only-missing` writes only docs/blobs absent from the new partition: use it for the second pass after the deploy, so it can never clobber edits made through the new code.

- [ ] **Step 1: Write the failing test** (`tests/test_migrate_to_users.py`)

```python
import importlib.util
import pathlib

import pytest

from app import blobstore, db
from tests.helpers import TEST_USER, wipe_users

spec = importlib.util.spec_from_file_location(
    "migrate", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "migrate-to-users.py")
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


@pytest.fixture
def setup():
    db.init()
    wipe_users()
    client = db.get_conn()
    for name in migrate.COLLECTIONS:
        for d in client.collection(name).stream():
            d.reference.delete()
    yield client
    db.teardown()


def test_copies_collections_and_blobs_and_keeps_the_old_ones(setup):
    client = setup
    client.collection("todos").document("t1").set({"todo_id": "t1", "title": "old"})
    client.collection("meta").document("rev").set({"value": 7})
    client.collection("push_devices").document("d1").set({"token": "tok"})
    store = blobstore.use_memory()
    store.put("todos/t1/a1", b"img", "image/png")

    out = migrate.migrate(client, store, TEST_USER, dry_run=False)

    user = client.collection("users").document(TEST_USER)
    assert user.collection("todos").document("t1").get().to_dict()["title"] == "old"
    assert user.collection("meta").document("rev").get().to_dict() == {"value": 7}
    assert store.get(f"users/{TEST_USER}/todos/t1/a1") == (b"img", "image/png")
    assert client.collection("todos").document("t1").get().exists  # old data stays until you delete it
    assert store.get("todos/t1/a1") is not None
    assert out["docs"] == 3 and out["blobs"] == 1


def test_dry_run_writes_nothing(setup):
    client = setup
    client.collection("todos").document("t1").set({"todo_id": "t1"})
    out = migrate.migrate(client, blobstore.use_memory(), TEST_USER, dry_run=True)
    assert out["docs"] == 1
    assert not client.collection("users").document(TEST_USER).collection("todos").document("t1").get().exists


def test_rerun_picks_up_writes_made_since_and_only_missing_keeps_new_edits(setup):
    client = setup
    store = blobstore.use_memory()
    client.collection("todos").document("t1").set({"todo_id": "t1", "title": "v1"})
    migrate.migrate(client, store, TEST_USER, dry_run=False)
    # the old service keeps writing until the deploy
    client.collection("todos").document("t2").set({"todo_id": "t2", "title": "late"})
    # ...and after the deploy the new code edits t1 in the new partition
    dest = client.collection("users").document(TEST_USER).collection("todos")
    dest.document("t1").set({"todo_id": "t1", "title": "edited in new app"})
    migrate.migrate(client, store, TEST_USER, dry_run=False, only_missing=True)
    assert dest.document("t2").get().to_dict()["title"] == "late"
    assert dest.document("t1").get().to_dict()["title"] == "edited in new app"
```

- [ ] **Step 2: Run to verify failure**

Run: `scripts/test.sh tests/test_migrate_to_users.py`
Expected: FAIL (`FileNotFoundError` for the script).

- [ ] **Step 3: Implement** `scripts/migrate-to-users.py`

```python
#!/usr/bin/env python3
"""One-off: copy the pre-multi-user data (top-level todos, todos_archive, txn_log, meta,
push_devices, push_sent, and blobs under todos/) into users/{OWNER}/…. Dry run unless
--apply. Copies only: the old data is left in place so you can roll back; delete it by
hand after you have verified the app (see docs/okf/ops/multi-user.md). Safe to re-run
(overwrites from the old data); after the deploy use --only-missing so nothing edited
through the new code is overwritten.

Run against production with real credentials:
  GOOGLE_CLOUD_PROJECT=<project> ATTACHMENTS_BUCKET=<bucket> python scripts/migrate-to-users.py you@example.com --apply
Take a backup first: gcloud firestore export gs://<bucket>/backup-$(date +%F)
"""
from __future__ import annotations

import sys

COLLECTIONS = ("todos", "todos_archive", "txn_log", "meta", "push_devices", "push_sent")
BATCH = 400  # Firestore allows 500 writes per batch


def migrate(client, store, owner: str, dry_run: bool, only_missing: bool = False) -> dict:
    owner = owner.strip().lower()
    dest = client.collection("users").document(owner)
    docs = blobs = 0
    for name in COLLECTIONS:
        batch, pending = client.batch(), 0
        for snap in client.collection(name).stream():
            if only_missing and dest.collection(name).document(snap.id).get().exists:
                continue
            docs += 1
            if dry_run:
                continue
            batch.set(dest.collection(name).document(snap.id), snap.to_dict())
            pending += 1
            if pending == BATCH:
                batch.commit()
                batch, pending = client.batch(), 0
        if pending:
            batch.commit()
    for key, _created in store.list_blobs("todos/"):
        if only_missing and store.get(f"users/{owner}/{key}") is not None:
            continue
        blobs += 1
        if dry_run:
            continue
        data, content_type = store.get(key)
        store.put(f"users/{owner}/{key}", data, content_type)
    return {"docs": docs, "blobs": blobs, "dry_run": dry_run}


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    from google.cloud import firestore

    from app import blobstore
    result = migrate(firestore.Client(), blobstore.get_store(), argv[0], dry_run="--apply" not in argv,
                     only_missing="--only-missing" in argv)
    print(result, "(dry run: nothing written; pass --apply)" if result["dry_run"] else "(copied)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Note `store.get(key)` returns `(bytes, content_type) | None` (see `MemoryStore.get`); `GcsStore.get` has the same contract. Blobs under `users/…` are not matched by `list_blobs("todos/")`, so a rerun after `--apply` does not recurse.

- [ ] **Step 4: Run to verify pass**

Run: `scripts/test.sh tests/test_migrate_to_users.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate-to-users.py tests/test_migrate_to_users.py
git commit -m "Add one-off script to copy existing data into the owner's partition"
```

---

### Task 5: Config, docs, deploy and verification in Chrome

**Note:** this plan does not address a shared device used by more than one family member (the previous-person's-outbox / stale-push-token problem) — out of scope by explicit request. Each person is expected to use their own device.

**Files:**
- Modify: `deploy.sh:15-18`, `run.sh:4`, `.now.env.example:8`, `scripts/doctor.sh:42`, `scripts/init.sh:37-45`, `scripts/migrate-service.sh:45-51`, `README.md:21,230,237`
- Modify: `docs/okf/principles.md`, `docs/okf/architecture/stack.md`, `docs/okf/data/firestore.md`, `docs/okf/api/routes.md`, `docs/okf/features/ui-inventory.md`, `docs/okf/features/push-reminders.md`, `docs/okf/features/calendar-feed.md`, `docs/okf/features/attachments.md`, `docs/okf/ops/deploy.md`, `docs/okf/ops/forking.md`, `docs/okf/ops/local-browser-testing.md`, `docs/okf/index.md`, `docs/okf/log.md`
- Create: `docs/okf/ops/multi-user.md`

- [ ] **Step 1: Env var plumbing.** `deploy.sh` (lines 16-18: both the env var and the `_cfg .now.env` key): read `ALLOWED_EMAILS` (fallback `ALLOWED_EMAIL`) and write `ALLOWED_EMAILS=${ALLOWED_EMAILS}` into `env_vars` (values use `;` between emails, since `env_vars` is comma-joined). Same for `run.sh` (`: "${ALLOWED_EMAILS:-${ALLOWED_EMAIL:?export ALLOWED_EMAILS=you@example.com;kid@example.com}}"` then `export ALLOWED_EMAILS`), `.now.env.example`, `scripts/doctor.sh` (accept either name), `scripts/init.sh` (prompt text "Google accounts allowed to sign in (first is the owner, separate with ;)"), `scripts/migrate-service.sh` (copy whichever name the old service has), `README.md`. Afterwards run `grep -rn ALLOWED_EMAIL . --exclude-dir=.git --exclude-dir=.claude --exclude-dir=graphify-out` and check every remaining hit is intentional (legacy fallback or docs). The running service already has legacy `ALLOWED_EMAIL`, which `app/auth.py` still reads, so deploying this code changes nothing until you set `ALLOWED_EMAILS`.

- [ ] **Step 2: OKF bundle** (same commit; bump each `timestamp`; append a dated line per file changed to `docs/okf/log.md`):
  - `principles.md`: replace "One user, by design … Multi-tenancy is a non-goal" with: one *deployment* serves a family; each person's data is isolated by email; still no sharing, roles or invite UI; access is the `ALLOWED_EMAILS` list. Keep the cost rule and add: reads scale with number of users.
  - `stack.md` (Auth), `zilch-gcp.md` env list: `ALLOWED_EMAILS`.
  - `data/firestore.md`: new layout `users/{email}/{todos,todos_archive,txn_log,meta,push_devices,push_sent}`.
  - `api/routes.md`: widget/calendar/budget are owner-only; `/internal/notify` loops users; heads-up task body has `user`.
  - `features/calendar-feed.md`, `push-reminders.md`, `attachments.md` (blob key layout).
  - `features/ui-inventory.md`: line "Calendar link in More: shown to the owner only".
  - `ops/multi-user.md` (new, `type: Runbook`): adding a person (redeploy with the new list), running the migration (`gcloud firestore export` backup → dry run → `--apply` → verify → delete old top-level collections and `todos/` blobs by hand), the widget/calendar being owner-only, and a note that a device shared between two family members is out of scope (each person uses their own device). Link it from `index.md`.
  - `ops/local-browser-testing.md`: checklist items below.

- [ ] **Step 3: Full checks**

Run: `scripts/test.sh && npm test && ruff check . && git diff --stat`
Expected: all green; no changes outside the listed files.

- [ ] **Step 4: Browser verification in Chrome (required by project rules, use the `claude-in-chrome` skill).** Start the local server with two emails in `ALLOWED_EMAILS` (see `docs/okf/ops/local-browser-testing.md`) and check:
  1. Sign in as the owner: existing UI checklist passes (add, edit, complete, reorder, trash/undelete, search, More panel incl. calendar link, attachments).
  2. Sign in as the second email (a separate browser profile or device — a shared device is out of scope): an empty list appears; the owner's todos are absent; the More panel has **no** calendar link; adding a todo does not appear for the owner when signed in there.

- [ ] **Step 5: Deploy (only with the user's go-ahead; this needs the migration done first).** Order matters: (a) `gcloud firestore export` backup; (b) `python scripts/migrate-to-users.py OWNER` dry run, then `--apply`, **immediately** before (c), because the old service keeps writing to the old collections until the deploy finishes; (c) `ALLOWED_EMAILS='owner;kid' ./deploy.sh`; (c2) right after, `--apply --only-missing` to copy anything created in the gap (never overwrites what the new code has since edited); (d) verify as owner: old todos and images present; (e) only then delete the old top-level collections and `todos/` blobs. Per the memory note for this project: run `say` when the deploy is finished. Add a line to `scripts/cost-check.sh` output or the OKF cost section noting the per-user read scaling (no code guard needed at family size; the existing 24 h read-vs-quota warning already covers it). Report the read-cost point (one tree read per user per rev change) to the user, loudly, in the summary.

- [ ] **Step 6: Commit**

```bash
git add -A docs deploy.sh run.sh .now.env.example scripts README.md
git commit -m "Multi-user: ALLOWED_EMAILS config, OKF bundle and runbook"
```

---

## Self-Review

- **Spec coverage:** partition todos/archive/txn_log/rev/push/blobs (Task 2); auth for several emails and per-request binding (Task 1); notifications, heads-ups, calendar and owner-only tokens (Task 3); migration of existing data (Task 4, user chose to migrate); env-list access (user chose it; Task 5); no sharing (Global Constraints); docs/principles (Task 5). Out of scope by explicit request: a device shared by two family members.
- **Placeholders:** none intended; the mechanical `sed` replacements in Task 2 are followed by a grep that must come back clean.
- **Type consistency:** `tenant.current()/set_user()/reset()/as_user()`, `auth.ALLOWED_EMAILS/owner()/bind_user()/calendar_feed_path(user)`, `db.user_ref(email=None)`, `blobstore.user_todos_prefix()/key_for()/todo_prefix()`, `HeadsUp.user`, `migrate(client, store, owner, dry_run, only_missing)` are used with the same names in every task.
- **Known risks called out:** ContextVar propagation into sync routes has its own test in Task 1 and a fallback; the migration must run before the new code serves traffic; a first-deploy with only legacy `ALLOWED_EMAIL` still works (single owner).
