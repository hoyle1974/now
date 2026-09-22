# Calendar Item Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `calendar` item type that syncs an external ICS feed URL into read-only `calendar_event` children, triggered by use (not a cron job), with a manual "Sync now" button and a digest-job nudge for staleness.

**Architecture:** Two new entries in the existing type registry (`app/types.json` → `web/types-data.js`), a new pure ICS-parsing/diffing module (`app/calendar_sync.py`), a DB reconciliation function that writes through the normal todo create/update/delete path (so `/todos/rev` bumps and the existing client freshness poll picks up changes), and a Cloud Task (reusing the existing reminder queue/OIDC plumbing in `app/tasks.py`) for the actual fetch so it never blocks a page load.

**Tech Stack:** FastAPI, Firestore, `icalendar` + `recurring-ical-events` (new deps) for ICS parsing/recurrence expansion, Google Cloud Tasks (existing queue), vanilla JS client (`web/*.js`, classic scripts).

**Spec:** `docs/superpowers/specs/2026-09-22-calendar-type-design.md`

## Global Constraints

- No new scheduled job / cron / Cloud Scheduler entry. Sync is triggered by: (a) a stale `calendar` appearing in a `GET /todos/tree` or `GET /todos/root` response, (b) the manual "Sync now" button, (c) the daily digest job noticing a stale calendar while it's already walking the tree.
- Staleness threshold: **6 hours** (`last_synced_at` null or older).
- On fetch/parse failure: existing `calendar_event`s are left untouched; `last_sync_error` is set; `last_synced_at` **is still updated** (so a broken feed is retried once per staleness window, not every page load).
- Sync window: recurring events expanded to individual occurrences, **60 days ahead, no past**.
- `calendar_event`s are read-only in the UI: no edit sheet, no manual move/delete, no type switch.
- A `calendar` item rejects user-created children (`POST /todos` + reparent + split targeting it as parent get 400) — enforced at the HTTP route layer; the sync module writes children by calling `app/db_firestore.py` functions directly, never through the routes, so it needs no bypass.
- Reuse existing infra: the same Cloud Tasks queue/OIDC caller env vars used for heads-up reminders (`REMINDER_QUEUE`, `NOTIFY_AUDIENCE`, `NOTIFY_CALLER`) — no new env vars, no new queue.
- Every task that touches `docs/okf/` content does so in the same commit as the code change (project rule, `CLAUDE.md`).

---

## Task 1: Registry — `calendar` and `calendar_event` types

**Files:**
- Modify: `app/types.json`
- Modify: `app/models.py` (`ItemType` Literal, `Todo`, `TodoUpdate`)
- Modify: `app/db_firestore_helpers.py` (`doc_to_todo`, `todo_to_doc`)
- Modify: `web/types-data.js` (generated — run `python scripts/gen_types.py`, don't hand-edit)
- Modify: `tests/test_item_types.py`
- Test: `tests/test_item_types.py`

**Interfaces:**
- Produces: registry flags `allowsUserChildren` (bool, on every type from now on) and `editable` (bool, on every type from now on); `types.can_type(name, "allowsUserChildren")` / `types.can_type(name, "editable")` usable by later tasks. New `Todo` fields: `calendar_url: str | None`, `location: str | None`, `external_uid: str | None`, `last_synced_at: datetime | None`, `last_sync_error: str | None`. New `TodoUpdate` field: `calendar_url: str | None` (user-editable; the other four are server-managed only, never in `TodoUpdate`).

- [ ] **Step 1: Write the failing registry test**

Add to `tests/test_item_types.py` (near `test_registry_has_the_three_types_and_flags`):

```python
def test_registry_has_calendar_types_and_new_flags():
    assert {"calendar", "calendar_event"} <= set(types.NAMES)
    for name in types.NAMES:
        assert "allowsUserChildren" in types.caps(name)
        assert "editable" in types.caps(name)
    assert types.can_type("todo", "allowsUserChildren") is True
    assert types.can_type("calendar", "allowsUserChildren") is False
    assert types.can_type("calendar_event", "allowsUserChildren") is False
    assert types.can_type("calendar_event", "editable") is False
    assert types.can_type("calendar", "editable") is True
    assert types.has_field_type("calendar", "calendar_url")
    assert types.has_field_type("calendar_event", "location")
    assert types.has_field_type("calendar_event", "due_date")
    assert types.can_type("calendar_event", "hasCheckbox") is False
    assert types.can_type("calendar_event", "appearsInNextUp") is True
    assert types.can_type("calendar_event", "notifies") is True
    assert types.can_type("calendar", "appearsInNextUp") is False
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `scripts/test.sh -k test_registry_has_calendar_types_and_new_flags`
Expected: FAIL (`calendar` not in `types.NAMES`, `KeyError: 'allowsUserChildren'`)

- [ ] **Step 3: Update `app/types.json`**

Add `"allowsUserChildren": true, "editable": true` to the existing `todo`, `list` and `project` entries (every existing type keeps current behaviour), then add two new entries:

```json
  "calendar": {
    "label": "Calendar",
    "icon": "calendar",
    "fields": ["title", "calendar_url", "color", "links", "references", "attachments"],
    "hasCheckbox": false,
    "appearsInNextUp": false,
    "triggersAutodone": false,
    "countsInBadge": false,
    "showsProgress": false,
    "notifies": false,
    "allowsUserChildren": false,
    "editable": true,
    "description": "A live calendar feed; its events sync in automatically.",
    "defaultChildType": "calendar_event"
  },
  "calendar_event": {
    "label": "Event",
    "icon": "calendar",
    "fields": ["title", "due_date", "location"],
    "hasCheckbox": false,
    "appearsInNextUp": true,
    "triggersAutodone": false,
    "countsInBadge": false,
    "showsProgress": false,
    "notifies": true,
    "allowsUserChildren": false,
    "editable": false,
    "description": "One event from a synced calendar. Read-only.",
    "defaultChildType": "calendar_event"
  }
```

- [ ] **Step 4: Update `app/models.py`**

`ItemType`: `ItemType = Literal["todo", "list", "project", "calendar", "calendar_event"]  # keep in step with app/types.json`

In `Todo`, after the `attachments` field:

```python
    calendar_url: str | None = Field(None)  # calendar type: the source ICS feed URL
    location: str | None = Field(None)      # calendar_event type: from the source ICS event
    external_uid: str | None = Field(None)  # calendar_event type: stable id from the source feed, for sync matching
    last_synced_at: datetime.datetime | None = Field(None)  # calendar type: server-managed
    last_sync_error: str | None = Field(None)  # calendar type: server-managed
```

In `TodoUpdate`, after `type`:

```python
    calendar_url: str | None = Field(None, max_length=models.MAX_URL_LEN if False else 2048)  # replace below
```

Actually write it plainly (no forward reference needed, `MAX_URL_LEN` is already module-level):

```python
    calendar_url: str | None = Field(None, max_length=MAX_URL_LEN)  # explicit null clears

    @field_validator("calendar_url")
    @classmethod
    def _check_calendar_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        u = urlparse(v)
        if not v or u.scheme not in ("http", "https") or not u.netloc:
            raise ValueError("calendar_url must be an http(s) URL")
        return v
```

- [ ] **Step 5: Update `app/db_firestore_helpers.py`**

In `doc_to_todo`, after `attachments=...`:

```python
        calendar_url=doc_dict.get("calendar_url"),
        location=doc_dict.get("location"),
        external_uid=doc_dict.get("external_uid"),
        last_synced_at=(None if doc_dict.get("last_synced_at") is None
                        else datetime.datetime.fromisoformat(doc_dict["last_synced_at"])),
        last_sync_error=doc_dict.get("last_sync_error"),
```

In `todo_to_doc`, after `"attachments": ...`:

```python
        "calendar_url": todo.calendar_url,
        "location": todo.location,
        "external_uid": todo.external_uid,
        "last_synced_at": None if todo.last_synced_at is None else todo.last_synced_at.isoformat(),
        "last_sync_error": todo.last_sync_error,
```

- [ ] **Step 6: Regenerate the client registry**

Run: `python scripts/gen_types.py`

This rewrites `web/types-data.js` from `app/types.json`; do not hand-edit that file.

- [ ] **Step 7: Run the test, confirm it passes**

Run: `scripts/test.sh -k test_registry_has_calendar_types_and_new_flags`
Expected: PASS. Also run the full type-registry file to catch regressions: `scripts/test.sh tests/test_item_types.py -v` — expect all PASS (the file's stale-generated-file check now also passes since Step 6 regenerated it).

- [ ] **Step 8: Commit**

```bash
git add app/types.json app/models.py app/db_firestore_helpers.py web/types-data.js tests/test_item_types.py
git commit -m "feat: add calendar and calendar_event to the item type registry

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Server — reject user-created children under `allowsUserChildren: false`

**Files:**
- Modify: `app/routes/todos.py` (`split_todo`, `reparent_todo`)
- Test: `tests/test_item_types.py`

**Interfaces:**
- Consumes: `types.can_type(name, "allowsUserChildren")` from Task 1; `db.get_todo` (existing).
- Produces: nothing new consumed elsewhere; this is a leaf enforcement point.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_item_types.py`:

```python
def test_split_rejects_a_no-children-parent():
    pass  # placeholder name fixed below
```

Actually use valid Python identifiers — add this block instead:

```python
def test_split_rejected_under_calendar(db_setup):
    parent = models.Todo(title="Family calendar", type="calendar")
    db.create_todo(parent)
    resp = client.post(f"/todos/{parent.todo_id}/split", json={"descriptions": ["x"]},
                       headers={"Authorization": "Bearer test", "X-Txn-Id": "t1"})
    assert resp.status_code == 400
    assert "does not accept" in resp.json()["detail"]

def test_reparent_rejected_under_calendar(db_setup):
    parent = models.Todo(title="Family calendar", type="calendar")
    db.create_todo(parent)
    child = models.Todo(title="a todo")
    db.create_todo(child)
    resp = client.patch(f"/todos/{child.todo_id}/reparent", json={"parent_id": str(parent.todo_id)},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400
    assert "does not accept" in resp.json()["detail"]

def test_reparent_to_top_level_still_allowed(db_setup):
    """Sanity: the guard only fires for a real parent_id, not parent_id: null."""
    child = models.Todo(title="a todo", parent_id=None)
    db.create_todo(child)
    resp = client.patch(f"/todos/{child.todo_id}/reparent", json={"parent_id": None},
                        headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200
```

(Check the file's existing auth pattern for `client.post`/`client.patch` calls — `tests/helpers.py`'s `act_as(app)` overrides the auth dependency for the whole test module, so the `Authorization` header shown above is what other tests in this file already send; match that exactly rather than guessing — grep `tests/test_item_types.py` for an existing `client.patch(` call and copy its header style.)

- [ ] **Step 2: Run tests, confirm they fail**

Run: `scripts/test.sh -k "rejected_under_calendar or top_level_still_allowed"`
Expected: FAIL (both rejects currently return 200; split creates children, reparent succeeds)

- [ ] **Step 3: Implement the guard in `app/routes/todos.py`**

Add a small helper near the top of the file (after imports):

```python
def _check_accepts_children(parent_id) -> None:
    if parent_id is None:
        return
    parent = db.get_todo(models.TodoId(parent_id) if not isinstance(parent_id, models.TodoId) else parent_id)
    if parent is not None and not types.can(parent, "allowsUserChildren"):
        raise HTTPException(400, f"{types.caps(parent.type)['label']} does not accept added items")
```

In `split_todo`, right after the `due_date = ...` line and before `def action`:

```python
    _check_accepts_children(todo_id)
```

(`todo_id` here is the raw `uuid.UUID` path param — `_check_accepts_children` handles wrapping it.)

In `reparent_todo`, at the top of `action`, before the `try:`:

```python
        _check_accepts_children(body.parent_id)
```

- [ ] **Step 4: Run tests, confirm they pass**

Run: `scripts/test.sh -k "rejected_under_calendar or top_level_still_allowed"`
Expected: PASS

- [ ] **Step 5: Run the full Python suite to catch regressions**

Run: `scripts/test.sh`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add app/routes/todos.py tests/test_item_types.py
git commit -m "feat: reject split/reparent under a type that disallows user children

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: ICS parsing and diff — `app/calendar_sync.py` (pure logic)

**Files:**
- Create: `app/calendar_sync.py`
- Create: `tests/fixtures/calendar/simple.ics`
- Create: `tests/fixtures/calendar/recurring.ics`
- Create: `tests/fixtures/calendar/allday.ics`
- Modify: `requirements.in`, `requirements.txt`
- Test: `tests/test_calendar_sync.py`

**Interfaces:**
- Produces:
  - `ParsedEvent` (dataclass): `external_uid: str`, `title: str`, `due_date: datetime.datetime`, `location: str | None`
  - `parse_ics(raw: str, window_start: datetime.date, window_end: datetime.date) -> list[ParsedEvent]` — parses, expands recurrence, clips to `[window_start, window_end)`. Raises `CalendarSyncError` on unparseable input.
  - `CalendarSyncError(Exception)`
  - `diff_events(desired: list[ParsedEvent], existing: dict[str, models.Todo]) -> tuple[list[ParsedEvent], list[tuple[str, ParsedEvent]], list[str]]` — returns `(to_create, to_update, to_delete_ids)`. `existing` is keyed by `external_uid`. `to_update` pairs an existing todo's id with the new `ParsedEvent` data (only entries whose title/due_date/location actually changed).
- Consumes: nothing project-specific — pure parsing/diffing, no DB, no network (network fetch is Task 5's job).

- [ ] **Step 1: Add the parsing dependencies**

In `requirements.in`, add two lines (alphabetical, matching the file's existing style):

```
icalendar==6.1.1
recurring-ical-events==2.2.4
```

Run: `pip install icalendar==6.1.1 recurring-ical-events==2.2.4` (dev env), and if the project uses `uv pip compile` to regenerate the lock (per `requirements.txt`'s header comment), run:

```bash
uv pip compile requirements.in -o requirements.txt --python-version 3.13 --universal
```

If `uv` isn't available in this environment, hand-add the two resolved lines to `requirements.txt` in the same alphabetical position as the other entries, with no `# via` comment needed beyond `# via -r requirements.in` (matching the style of `fastapi==...`).

- [ ] **Step 2: Write the ICS fixtures**

`tests/fixtures/calendar/simple.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//test//EN
BEGIN:VEVENT
UID:event-1@example.com
DTSTAMP:20260101T000000Z
DTSTART:20260201T150000
DTEND:20260201T160000
SUMMARY:Dentist
LOCATION:123 Main St
END:VEVENT
BEGIN:VEVENT
UID:event-2@example.com
DTSTAMP:20260101T000000Z
DTSTART:20260203T090000
DTEND:20260203T093000
SUMMARY:Standup
END:VEVENT
END:VCALENDAR
```

`tests/fixtures/calendar/recurring.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//test//EN
BEGIN:VEVENT
UID:weekly-meeting@example.com
DTSTAMP:20260101T000000Z
DTSTART:20260202T100000
DTEND:20260202T103000
RRULE:FREQ=WEEKLY;COUNT=8
SUMMARY:Team sync
END:VEVENT
END:VCALENDAR
```

`tests/fixtures/calendar/allday.ics`:

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//test//EN
BEGIN:VEVENT
UID:birthday@example.com
DTSTAMP:20260101T000000Z
DTSTART;VALUE=DATE:20260210
DTEND;VALUE=DATE:20260211
SUMMARY:Sam's birthday
END:VEVENT
END:VCALENDAR
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_calendar_sync.py`:

```python
import datetime as dt
from pathlib import Path

import pytest

from app import calendar_sync, models

FIXTURES = Path(__file__).parent / "fixtures" / "calendar"


def read(name):
    return (FIXTURES / name).read_text()


def test_parse_simple_events_in_window():
    events = calendar_sync.parse_ics(read("simple.ics"), dt.date(2026, 1, 1), dt.date(2026, 3, 1))
    assert {e.external_uid for e in events} == {"event-1@example.com", "event-2@example.com"}
    dentist = next(e for e in events if e.external_uid == "event-1@example.com")
    assert dentist.title == "Dentist"
    assert dentist.location == "123 Main St"
    assert dentist.due_date == dt.datetime(2026, 2, 1, 15, 0, 0)


def test_parse_clips_to_window():
    events = calendar_sync.parse_ics(read("simple.ics"), dt.date(2026, 1, 1), dt.date(2026, 2, 2))
    assert {e.external_uid for e in events} == {"event-1@example.com"}  # event-2 is Feb 3, outside


def test_parse_expands_recurrence_into_occurrences():
    events = calendar_sync.parse_ics(read("recurring.ics"), dt.date(2026, 1, 1), dt.date(2026, 4, 1))
    assert len(events) == 8
    uids = {e.external_uid for e in events}
    assert len(uids) == 8  # each occurrence gets a distinct uid
    assert all(e.title == "Team sync" for e in events)
    assert sorted(e.due_date for e in events)[0] == dt.datetime(2026, 2, 2, 10, 0, 0)


def test_parse_all_day_event_is_midnight():
    events = calendar_sync.parse_ics(read("allday.ics"), dt.date(2026, 1, 1), dt.date(2026, 3, 1))
    assert events[0].due_date == dt.datetime(2026, 2, 10, 0, 0, 0)


def test_parse_bad_input_raises():
    with pytest.raises(calendar_sync.CalendarSyncError):
        calendar_sync.parse_ics("not an ics file", dt.date(2026, 1, 1), dt.date(2026, 3, 1))


def _todo(uid, title, due, location=None):
    return models.Todo(title=title, type="calendar_event", external_uid=uid,
                       due_date=due, location=location)


def test_diff_creates_updates_deletes():
    kept = calendar_sync.ParsedEvent("kept@x", "Same", dt.datetime(2026, 2, 1, 9), None)
    changed = calendar_sync.ParsedEvent("changed@x", "New title", dt.datetime(2026, 2, 2, 9), None)
    new = calendar_sync.ParsedEvent("new@x", "Brand new", dt.datetime(2026, 2, 3, 9), None)
    existing = {
        "kept@x": _todo("kept@x", "Same", dt.datetime(2026, 2, 1, 9)),
        "changed@x": _todo("changed@x", "Old title", dt.datetime(2026, 2, 2, 9)),
        "gone@x": _todo("gone@x", "No longer in feed", dt.datetime(2026, 2, 5, 9)),
    }
    to_create, to_update, to_delete = calendar_sync.diff_events([kept, changed, new], existing)
    assert to_create == [new]
    assert [u for _, u in to_update] == [changed]
    assert to_delete == [str(existing["gone@x"].todo_id)]
```

- [ ] **Step 4: Run tests, confirm they fail**

Run: `scripts/test.sh tests/test_calendar_sync.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.calendar_sync'`)

- [ ] **Step 5: Implement `app/calendar_sync.py`**

```python
"""Pure ICS parsing and diffing for the calendar item type: no DB, no network
(app/tasks.py fetches; this module only turns bytes into ParsedEvents and
ParsedEvents-vs-existing-Todos into a create/update/delete plan)."""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from app import models


class CalendarSyncError(Exception):
    """The feed could not be parsed."""


@dataclass(frozen=True)
class ParsedEvent:
    external_uid: str
    title: str
    due_date: datetime.datetime  # naive; all-day events are midnight (matches due-time.md convention)
    location: str | None


def parse_ics(raw: str, window_start: datetime.date, window_end: datetime.date) -> list[ParsedEvent]:
    """Every occurrence (recurring events expanded) starting in [window_start, window_end)."""
    import icalendar
    import recurring_ical_events

    try:
        cal = icalendar.Calendar.from_ical(raw)
    except Exception as e:
        raise CalendarSyncError(f"could not parse calendar: {e}") from e

    try:
        occurrences = recurring_ical_events.of(cal).between(window_start, window_end)
    except Exception as e:
        raise CalendarSyncError(f"could not expand recurrence: {e}") from e

    events: list[ParsedEvent] = []
    for i, occ in enumerate(occurrences):
        start = occ["DTSTART"].dt
        all_day = not isinstance(start, datetime.datetime)
        due = (datetime.datetime.combine(start, datetime.time(0, 0)) if all_day
               else start.replace(tzinfo=None) if start.tzinfo is None
               else start.astimezone(datetime.UTC).replace(tzinfo=None))
        base_uid = str(occ.get("UID", ""))
        if not base_uid:
            continue  # an event with no UID can never be matched on the next sync; skip it
        # One base UID can produce several occurrences; make each stable across syncs by
        # folding the occurrence's own start time into the id (not the loop index, which
        # would shuffle if the feed reorders events between syncs).
        uid = f"{base_uid}:{due.isoformat()}"
        events.append(ParsedEvent(
            external_uid=uid,
            title=str(occ.get("SUMMARY", "")) or "(untitled event)",
            due_date=due,
            location=str(occ.get("LOCATION", "")).strip() or str(occ.get("DESCRIPTION", "")).strip() or None,
        ))
    return events


def diff_events(desired: list[ParsedEvent], existing: dict[str, models.Todo],
                ) -> tuple[list[ParsedEvent], list[tuple[str, ParsedEvent]], list[str]]:
    """(to_create, to_update, to_delete_ids). existing is keyed by external_uid.
    to_update pairs the existing todo's id with the new data, only when something changed."""
    desired_by_uid = {e.external_uid: e for e in desired}

    to_create = [e for uid, e in desired_by_uid.items() if uid not in existing]
    to_update = [
        (str(existing[uid].todo_id), e)
        for uid, e in desired_by_uid.items()
        if uid in existing and (
            existing[uid].title != e.title
            or existing[uid].due_date != e.due_date
            or existing[uid].location != e.location
        )
    ]
    to_delete = [str(t.todo_id) for uid, t in existing.items() if uid not in desired_by_uid]
    return to_create, to_update, to_delete
```

- [ ] **Step 6: Run tests, confirm they pass**

Run: `scripts/test.sh tests/test_calendar_sync.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/calendar_sync.py tests/test_calendar_sync.py tests/fixtures/calendar requirements.in requirements.txt
git commit -m "feat: parse and diff ICS calendars (app/calendar_sync.py)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: DB reconciliation — write the diff, track sync state

**Files:**
- Modify: `app/db_firestore.py`
- Modify: `app/db.py` (thin re-export, if that's how other db functions are exposed — check the file first)
- Test: `tests/test_calendar_sync.py`

**Interfaces:**
- Consumes: `calendar_sync.ParsedEvent`, `calendar_sync.diff_events` (Task 3); `create_todo`, `update_todo`, `_todos()`, `_get`/`_set`/`_update` (existing, same file).
- Produces: `get_calendar_event_children(calendar_id: str) -> dict[str, models.Todo]` (keyed by `external_uid`, live children only). `apply_calendar_sync(calendar_id: str, events: list[calendar_sync.ParsedEvent]) -> dict` — writes the diff, returns `{"created": int, "updated": int, "deleted": int}`. `mark_calendar_synced(calendar_id: str, error: str | None) -> None` — sets `last_synced_at` (now) and `last_sync_error`.

First, check how `app/db.py` re-exports `app/db_firestore.py` (it's a 1.4K file — read it) so the new functions are wired the same way as the existing ones.

- [ ] **Step 1: Check `app/db.py`'s re-export pattern**

Run: `cat app/db.py` and confirm whether it's `from app.db_firestore import *` or an explicit list. Add the three new function names to that file the same way every other `db_firestore` function got there (if it's a wildcard import, no change needed there).

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_calendar_sync.py` (needs the `db_setup` fixture — copy it verbatim from `tests/test_item_types.py`'s `db_setup` fixture, including its imports):

```python
from app import db, tenant
from tests.helpers import TEST_USER, act_as, wipe_users


@pytest.fixture
def db_setup():
    from app.main import app as fastapi_app
    act_as(fastapi_app)
    db.init()
    wipe_users()
    token = tenant.set_user(TEST_USER)
    yield
    tenant.reset(token)
    db.teardown()


def test_apply_calendar_sync_creates_updates_deletes(db_setup):
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    kept = calendar_sync.ParsedEvent("kept@x", "Same", dt.datetime(2026, 2, 1, 9), None)
    db.apply_calendar_sync(str(cal.todo_id), [kept])

    changed = calendar_sync.ParsedEvent("kept@x", "Renamed", dt.datetime(2026, 2, 1, 9), "Room 2")
    new = calendar_sync.ParsedEvent("new@x", "Brand new", dt.datetime(2026, 2, 3, 9), None)
    result = db.apply_calendar_sync(str(cal.todo_id), [changed, new])

    assert result == {"created": 1, "updated": 1, "deleted": 0}
    children = db.get_calendar_event_children(str(cal.todo_id))
    assert set(children) == {"kept@x", "new@x"}
    assert children["kept@x"].title == "Renamed"
    assert children["kept@x"].location == "Room 2"
    assert children["kept@x"].type == "calendar_event"
    assert children["kept@x"].parent_id == cal.todo_id


def test_apply_calendar_sync_deletes_missing(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    db.apply_calendar_sync(str(cal.todo_id), [calendar_sync.ParsedEvent("gone@x", "Bye", dt.datetime(2026, 2, 1, 9), None)])
    result = db.apply_calendar_sync(str(cal.todo_id), [])
    assert result == {"created": 0, "updated": 0, "deleted": 1}
    assert db.get_calendar_event_children(str(cal.todo_id)) == {}


def test_mark_calendar_synced(db_setup):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    db.mark_calendar_synced(str(cal.todo_id), error="feed unreachable")
    refreshed = db.get_todo(cal.todo_id)
    assert refreshed.last_sync_error == "feed unreachable"
    assert refreshed.last_synced_at is not None

    db.mark_calendar_synced(str(cal.todo_id), error=None)
    refreshed = db.get_todo(cal.todo_id)
    assert refreshed.last_sync_error is None
```

- [ ] **Step 3: Run tests, confirm they fail**

Run: `scripts/test.sh tests/test_calendar_sync.py -v -k "sync_creates or sync_deletes or mark_calendar"`
Expected: FAIL (`AttributeError: module 'app.db' has no attribute 'apply_calendar_sync'`)

- [ ] **Step 4: Implement in `app/db_firestore.py`**

Add near `split_into_children` (same file, same conventions — read that function's neighborhood again for `_next_order_idx`/`create_todo` usage before writing this):

```python
def get_calendar_event_children(calendar_id: str) -> dict[str, models.Todo]:
    """Live calendar_event children of a calendar item, keyed by external_uid
    (children with no external_uid, which should not happen, are skipped)."""
    docs = _child_docs(calendar_id)
    out = {}
    for d in docs:
        if d.get("type") != "calendar_event" or not d.get("external_uid"):
            continue
        out[d["external_uid"]] = db_firestore_helpers.doc_to_todo(d)
    return out


def apply_calendar_sync(calendar_id: str, events) -> dict:
    """Reconcile a calendar's children to exactly `events` (calendar_sync.ParsedEvent list),
    matched by external_uid. Each create/update/delete is a normal todo write, so /todos/rev
    bumps and the existing freshness/remote-diff client machinery picks it up."""
    from app import calendar_sync
    existing = get_calendar_event_children(calendar_id)
    to_create, to_update, to_delete = calendar_sync.diff_events(events, existing)

    for event in to_create:
        child = models.Todo(title=event.title, type="calendar_event", parent_id=models.TodoId(uuid.UUID(calendar_id)),
                            due_date=event.due_date, external_uid=event.external_uid, location=event.location)
        create_todo(child)

    for todo_id, event in to_update:
        doc_ref = _todos().document(todo_id)
        snap = _get(doc_ref)
        if not snap.exists:
            continue
        todo = db_firestore_helpers.doc_to_todo(snap.to_dict())
        todo.title, todo.due_date, todo.location = event.title, event.due_date, event.location
        update_todo(todo)

    for todo_id in to_delete:
        doc_ref = _todos().document(todo_id)
        snap = _get(doc_ref)
        if snap.exists:
            todo = db_firestore_helpers.doc_to_todo(snap.to_dict())
            todo.deleted = True
            update_todo(todo)

    return {"created": len(to_create), "updated": len(to_update), "deleted": len(to_delete)}


def mark_calendar_synced(calendar_id: str, error: str | None) -> None:
    """Server-managed sync bookkeeping: skips If-Match/version bump (like `collapsed`),
    since this isn't user content and must never conflict with a concurrent user edit."""
    _update(_todos().document(calendar_id), {
        "last_synced_at": _now_utc().replace(tzinfo=None).isoformat(),
        "last_sync_error": error,
    })
```

Check whether `apply_calendar_sync`'s writes need to run inside `run_atomic` (all the other multi-write functions in this file, e.g. `split_into_children`, are called from inside a route's `db.run_atomic(...)` wrapper — but this function will be called from a background Cloud Task handler with no client watching for a version conflict). Since there's no concurrent user write racing a specific calendar's own sync (only this job writes calendar_event children), wrap the whole body in one `run_atomic(None, ...)` for atomicity of the rev bump, matching the project's existing pattern rather than leaving the several individual writes as separate implicit transactions. Adjust the implementation above to wrap `to_create`/`to_update`/`to_delete` handling in:

```python
def apply_calendar_sync(calendar_id: str, events) -> dict:
    from app import calendar_sync

    def action() -> tuple[int, dict | None]:
        existing = get_calendar_event_children(calendar_id)
        to_create, to_update, to_delete = calendar_sync.diff_events(events, existing)
        for event in to_create:
            child = models.Todo(title=event.title, type="calendar_event",
                                parent_id=models.TodoId(uuid.UUID(calendar_id)),
                                due_date=event.due_date, external_uid=event.external_uid, location=event.location)
            create_todo(child)
        for todo_id, event in to_update:
            snap = _get(_todos().document(todo_id))
            if not snap.exists:
                continue
            todo = db_firestore_helpers.doc_to_todo(snap.to_dict())
            todo.title, todo.due_date, todo.location = event.title, event.due_date, event.location
            update_todo(todo)
        for todo_id in to_delete:
            snap = _get(_todos().document(todo_id))
            if snap.exists:
                todo = db_firestore_helpers.doc_to_todo(snap.to_dict())
                todo.deleted = True
                update_todo(todo)
        return 200, {"created": len(to_create), "updated": len(to_update), "deleted": len(to_delete)}

    _, body, _, _ = run_atomic(None, action)
    return body
```

- [ ] **Step 5: Run tests, confirm they pass**

Run: `scripts/test.sh tests/test_calendar_sync.py -v`
Expected: PASS

- [ ] **Step 6: Run the full Python suite**

Run: `scripts/test.sh`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add app/db_firestore.py app/db.py tests/test_calendar_sync.py
git commit -m "feat: reconcile calendar_event children through the normal write path

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Cloud Task enqueue + internal sync endpoint

**Files:**
- Modify: `app/tasks.py`
- Modify: `app/auth.py` (`_SCHEDULER_PATHS`)
- Modify: `app/routes/notifications.py`
- Create: `app/routes/calendar_sync_route.py` — actually keep it in `notifications.py` (it already holds every other `/internal/*` route; follow that convention, no new file)
- Test: `tests/test_tasks.py`, `tests/test_calendar_sync.py`

**Interfaces:**
- Produces: `tasks.create_calendar_sync_task(calendar_id: str, create: Callable | None = None) -> bool` (mirrors `create_task`'s shape). `tasks.enqueue_calendar_sync(calendar_id: str, last_synced_at, now_utc, threshold=STALE_AFTER, create=None) -> bool` — the one shared "is this stale, and if so enqueue" function every trigger (Task 6, 7, 8) calls. Route: `POST /internal/sync-calendar/{todo_id}` (body: `{"calendar_id": str, "user": str}`), OIDC-verified the same way `/internal/notify-todo` is.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tasks.py`:

```python
def test_enqueue_calendar_sync_stale_triggers():
    calls = []
    ok = tasks.enqueue_calendar_sync("cal-1", None, at("2026-02-01T00:00:00+00:00"),
                                     create=lambda cid: calls.append(cid) or True)
    assert ok is True
    assert calls == ["cal-1"]


def test_enqueue_calendar_sync_fresh_skips():
    calls = []
    recent = at("2026-02-01T00:00:00+00:00")
    ok = tasks.enqueue_calendar_sync("cal-1", recent, recent + dt.timedelta(hours=1),
                                     create=lambda cid: calls.append(cid) or True)
    assert ok is False
    assert calls == []


def test_enqueue_calendar_sync_exactly_at_threshold_triggers():
    base = at("2026-02-01T00:00:00+00:00")
    calls = []
    ok = tasks.enqueue_calendar_sync("cal-1", base, base + tasks.CALENDAR_STALE_AFTER,
                                     create=lambda cid: calls.append(cid) or True)
    assert ok is True
```

Add to `tests/test_calendar_sync.py` (needs `TestClient`, mirror `notify_todo`'s test in whichever file tests that — grep `tests/test_push_api.py` or `test_main.py` for `/internal/notify-todo` and copy its OIDC-mocking pattern exactly, since `verify_scheduler` needs `google.oauth2.id_token.verify_oauth2_token` mocked):

```python
def test_internal_sync_calendar_requires_scheduler_auth(db_setup):
    resp = client.post("/internal/sync-calendar/does-not-matter", json={"calendar_id": "x", "user": TEST_USER})
    assert resp.status_code in (401, 403)
```

(Leave the happy-path internal-endpoint test to Task 6's integration test, once `run_calendar_sync` exists to actually do something — this task only needs the auth gate proven.)

- [ ] **Step 2: Run tests, confirm they fail**

Run: `scripts/test.sh -k "enqueue_calendar_sync or internal_sync_calendar_requires"`
Expected: FAIL (`AttributeError: module 'app.tasks' has no attribute 'enqueue_calendar_sync'`; 404 instead of 401/403 for the missing route)

- [ ] **Step 3: Implement in `app/tasks.py`**

Add near `create_task`/`schedule_heads_up`:

```python
CALENDAR_STALE_AFTER = datetime.timedelta(hours=6)
SYNC_CALENDAR_PATH = "/internal/sync-calendar"


def _sync_task_name(queue: str, calendar_id: str, now_utc: datetime.datetime) -> str:
    # Bucketed by hour so two page loads in the same hour dedupe to one task
    # (Cloud Tasks refuses a duplicate name; AlreadyExists is swallowed below).
    bucket = now_utc.strftime("%Y%m%dT%H")
    return f"{queue}/tasks/calsync-{calendar_id}-{bucket}"


def create_calendar_sync_task(calendar_id: str, now_utc: datetime.datetime | None = None) -> bool:
    """Enqueue the sync Cloud Task for one calendar, to run right away.
    Reuses the reminder queue/OIDC plumbing (no new env vars). False when
    reminders aren't configured here; an existing task for this hour is fine."""
    global _client
    queue = os.environ.get("REMINDER_QUEUE", "")
    url = os.environ.get("NOTIFY_AUDIENCE", "").rstrip("/")
    caller = os.environ.get("NOTIFY_CALLER", "")
    if not (queue and url and caller):
        return False
    now_utc = now_utc or datetime.datetime.now(_UTC)
    from google.api_core import exceptions
    from google.cloud import tasks_v2
    if _client is None:
        _client = tasks_v2.CloudTasksClient()
    task = tasks_v2.Task(
        name=_sync_task_name(queue, calendar_id, now_utc),
        http_request=tasks_v2.HttpRequest(
            url=url + SYNC_CALENDAR_PATH + f"/{calendar_id}", http_method=tasks_v2.HttpMethod.POST,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"calendar_id": calendar_id, "user": tenant.current()}).encode(),
            oidc_token=tasks_v2.OidcToken(service_account_email=caller, audience=url)))
    with contextlib.suppress(exceptions.AlreadyExists):
        _client.create_task(request={"parent": queue, "task": task}, timeout=5)
    return True


def enqueue_calendar_sync(calendar_id: str, last_synced_at: datetime.datetime | None,
                          now_utc: datetime.datetime, threshold: datetime.timedelta = CALENDAR_STALE_AFTER,
                          create: Callable[[str], bool] | None = None) -> bool:
    """The one staleness check every trigger (list load, manual button, digest) shares.
    True when a sync was enqueued (or would have been, for the manual button which
    always calls this with last_synced_at forced stale)."""
    stale = last_synced_at is None or now_utc - last_synced_at >= threshold
    if not stale:
        return False
    try:
        return (create or create_calendar_sync_task)(calendar_id)
    except Exception:
        log.exception("calendar sync not enqueued for %s", calendar_id)
        return False
```

`tenant` is already imported in `app/tasks.py` (used by `create_task`'s body) — confirm before adding a duplicate import.

- [ ] **Step 4: Wire the internal endpoint's auth in `app/auth.py`**

In `_SCHEDULER_PATHS`, add the new path. Note it's a path *prefix* with a variable segment (`/internal/sync-calendar/{id}`), unlike the other three fixed paths — `require_user` does an exact-match `in` check, so extend it:

```python
_SCHEDULER_PATHS = {"/internal/notify", "/internal/notify-todo", "/internal/budget-alert"}
_SCHEDULER_PATH_PREFIXES = ("/internal/sync-calendar/",)
```

And in `require_user`:

```python
    if request.url.path in _SCHEDULER_PATHS or request.url.path.startswith(_SCHEDULER_PATH_PREFIXES):
        verify_scheduler(request)
        return
```

- [ ] **Step 5: Add the route in `app/routes/notifications.py`**

```python
@router.post("/internal/sync-calendar/{todo_id}")
def sync_calendar(todo_id: str, body: SyncCalendarBody) -> dict:
    """Cloud Tasks delivery for one calendar sync (OIDC-verified in require_user)."""
    from app import calendar_sync as _cs  # deferred: only this route needs the ICS parser
    user = (body.user or auth.owner()).lower()
    if user not in auth.ALLOWED_EMAILS:
        raise HTTPException(400, "unknown user")
    with tenant.as_user(user):
        return _cs.run_calendar_sync(body.calendar_id or todo_id)
```

Add the body model near `HeadsUp`'s sibling models at the top of the file:

```python
class SyncCalendarBody(BaseModel):
    calendar_id: str = Field(min_length=1, max_length=64)
    user: str | None = Field(None, max_length=320)
```

(`BaseModel`/`Field` need importing from `pydantic` in this file — check the current imports; `push.py` already imports them so this file may not yet.) `_cs.run_calendar_sync` doesn't exist yet — that's Task 6; for *this* task, stub it minimally so the route imports cleanly and the auth test in Step 1 passes:

Add to `app/calendar_sync.py` (end of file, temporary stub — Task 6 replaces the body):

```python
def run_calendar_sync(calendar_id: str) -> dict:
    """Stub; Task 6 fetches the feed and calls db.apply_calendar_sync."""
    return {"synced": False}
```

- [ ] **Step 6: Run tests, confirm they pass**

Run: `scripts/test.sh -k "enqueue_calendar_sync or internal_sync_calendar_requires"`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `scripts/test.sh`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add app/tasks.py app/auth.py app/routes/notifications.py app/calendar_sync.py tests/test_tasks.py tests/test_calendar_sync.py
git commit -m "feat: Cloud Task enqueue + internal endpoint for calendar sync

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Real fetch — `run_calendar_sync`, and wire staleness into `GET /todos/tree` / `/todos/root`

**Files:**
- Modify: `app/calendar_sync.py` (replace the Task 5 stub)
- Modify: `app/routes/todos.py` (`get_tree`, `list_todos`, new `POST /todos/{id}/sync`)
- Test: `tests/test_calendar_sync.py`

**Interfaces:**
- Consumes: `db.apply_calendar_sync`, `db.mark_calendar_synced`, `db.get_todo` (Task 4); `tasks.enqueue_calendar_sync` (Task 5).
- Produces: `calendar_sync.run_calendar_sync(calendar_id: str, fetch: Callable[[str], str] | None = None) -> dict` — fetches (via `fetch`, default `_http_fetch` using `urllib` or `requests`, which is already a transitive dep per `requirements.txt`), parses, diffs, writes, marks synced. Never raises (mirrors `push.py`'s "best-effort, never raises" internal-job convention) — catches everything, sets `last_sync_error`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_calendar_sync.py`:

```python
def test_run_calendar_sync_success(db_setup):
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    result = calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"))
    assert result["created"] == 2
    refreshed = db.get_todo(cal.todo_id)
    assert refreshed.last_sync_error is None
    assert refreshed.last_synced_at is not None


def test_run_calendar_sync_no_url_noops(db_setup):
    cal = models.Todo(title="Family", type="calendar")  # calendar_url never set
    db.create_todo(cal)
    result = calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=lambda url: (_ for _ in ()).throw(AssertionError("should not fetch")))
    assert result == {"synced": False, "reason": "no calendar_url"}


def test_run_calendar_sync_fetch_failure_keeps_existing_events(db_setup):
    cal = models.Todo(title="Family", type="calendar", calendar_url="https://example.com/f.ics")
    db.create_todo(cal)
    calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=lambda url: read("simple.ics"))
    before = db.get_calendar_event_children(str(cal.todo_id))

    def failing_fetch(url):
        raise OSError("network down")

    result = calendar_sync.run_calendar_sync(str(cal.todo_id), fetch=failing_fetch)
    assert result["synced"] is False
    after = db.get_calendar_event_children(str(cal.todo_id))
    assert set(after) == set(before)  # untouched
    refreshed = db.get_todo(cal.todo_id)
    assert "network down" in refreshed.last_sync_error
    assert refreshed.last_synced_at is not None  # updated even on failure, per spec
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `scripts/test.sh tests/test_calendar_sync.py -k run_calendar_sync -v`
Expected: FAIL (stub returns `{"synced": False}` unconditionally, no DB writes, `last_sync_error`/`last_synced_at` stay `None`)

- [ ] **Step 3: Implement `run_calendar_sync`**

`app/calendar_sync.py` currently starts with `from __future__ import annotations`, then `import datetime` and `from dataclasses import dataclass` (Task 3). Add `import uuid` and `from app import db, models` to that same top-of-file import block (a top-level `from app import db` is safe here: `app/db_firestore.py` only imports `calendar_sync` *inside* `apply_calendar_sync`'s function body, per Task 4, specifically to avoid this becoming a circular import).

Replace the Task 5 stub (`def run_calendar_sync(calendar_id: str) -> dict: ...`) at the end of the file with:

```python
WINDOW_DAYS = 60


def _http_fetch(url: str) -> str:
    import requests
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text


def run_calendar_sync(calendar_id: str, fetch=None) -> dict:
    """Fetch, parse, diff and write. Never raises: failure is recorded on the
    calendar item (last_sync_error) rather than propagated, so a Cloud Task
    delivery always acks and is never retried into a storm."""
    fetch = fetch or _http_fetch
    cal = db.get_todo(models.TodoId(uuid.UUID(calendar_id)))
    if cal is None:
        return {"synced": False, "reason": "calendar not found"}
    if not cal.calendar_url:
        return {"synced": False, "reason": "no calendar_url"}

    today = models.utc_now().date()
    window_end = today + datetime.timedelta(days=WINDOW_DAYS)
    try:
        raw = fetch(cal.calendar_url)
        events = parse_ics(raw, today, window_end)
    except Exception as e:
        db.mark_calendar_synced(calendar_id, error=str(e))
        return {"synced": False, "error": str(e)}

    result = db.apply_calendar_sync(calendar_id, events)
    db.mark_calendar_synced(calendar_id, error=None)
    return {"synced": True, **result}
```

Requirements: add `requests` — check `requirements.in`/`requirements.txt` first; `firebase-admin`/`google-cloud-storage` likely already pull in `requests` transitively (it showed up in Task 3's read of `requirements.txt`: `requests==2.34.2`). Since it's not a direct dependency today, add `requests==2.34.2` to `requirements.in` explicitly (relying on a transitive dependency for direct `import requests` use is fragile) and recompile per Task 3 Step 1's instructions.

- [ ] **Step 4: Run tests, confirm they pass**

Run: `scripts/test.sh tests/test_calendar_sync.py -v`
Expected: PASS

- [ ] **Step 5: Wire the staleness check into `GET /todos/tree` and `GET /todos/root`**

In `app/routes/todos.py`, add a helper (near `_housekeeping`):

```python
def _nudge_stale_calendars(todos: list[models.Todo] | dict, background: BackgroundTasks) -> None:
    """For each live `calendar` in a just-loaded tree/root list, enqueue a sync if stale.
    Runs as a background task (after the response is sent) so a slow/dead feed URL
    never adds latency to the read; the Cloud Task enqueue call itself is a fast
    Cloud Tasks API call, not the ICS fetch."""
    values = todos.values() if isinstance(todos, dict) else todos
    now = datetime.datetime.now(datetime.UTC)
    for t in values:
        if t.type == "calendar":
            background.add_task(tasks.enqueue_calendar_sync, str(t.todo_id), t.last_synced_at, now)
```

In `get_tree`, after `roots, todosById = _load_tree(rev, background)`:

```python
    _nudge_stale_calendars(todosById, background)
```

In `list_todos` (`GET /todos/root`), which currently has no `BackgroundTasks` param — add one:

```python
@router.get("/todos/root", response_model=list[models.Todo])
def list_todos(background: BackgroundTasks) -> list[models.Todo]:
    todos = db.get_root_todos()
    _nudge_stale_calendars(todos, background)
    return todos
```

(`get_next_up` deliberately excluded: it already calls `_load_tree`, but `calendar`s never `appearsInNextUp` so they're invisible there anyway; nudging on every Next Up poll would be redundant with the tree/root nudges without adding coverage.)

`background.add_task` runs `enqueue_calendar_sync` with **positional** args matching its signature `(calendar_id, last_synced_at, now_utc, threshold=..., create=...)` — confirm the call above matches (it does: `str(t.todo_id), t.last_synced_at, now`).

- [ ] **Step 6: Add the manual sync endpoint**

In `app/routes/todos.py`, near the other `/todos/{todo_id}/...` routes:

```python
@router.post("/todos/{todo_id}/sync", response_model=None)
def sync_now(todo_id: uuid.UUID, background: BackgroundTasks) -> Response:
    """Manual 'Sync now': enqueues immediately, ignoring staleness."""
    todo = db.get_todo(models.TodoId(todo_id))
    if todo is None:
        raise HTTPException(404, "todo not found")
    if todo.type != "calendar":
        raise HTTPException(400, "only a calendar item can be synced")
    background.add_task(tasks.enqueue_calendar_sync, str(todo.todo_id), None, datetime.datetime.now(datetime.UTC))
    return Response(status_code=202)
```

(Passing `last_synced_at=None` forces `enqueue_calendar_sync`'s staleness check to always trigger — matching the spec's "manual button always enqueues.")

- [ ] **Step 7: Write and run route-level tests**

Add to `tests/test_calendar_sync.py`:

```python
def test_sync_now_enqueues_for_calendar_type(db_setup, monkeypatch):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    calls = []
    monkeypatch.setattr(tasks, "create_calendar_sync_task", lambda cid: calls.append(cid) or True)
    resp = client.post(f"/todos/{cal.todo_id}/sync", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 202
    assert calls == [str(cal.todo_id)]


def test_sync_now_rejects_non_calendar(db_setup):
    t = models.Todo(title="a todo")
    db.create_todo(t)
    resp = client.post(f"/todos/{t.todo_id}/sync", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 400


def test_get_tree_nudges_stale_calendar(db_setup, monkeypatch):
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    calls = []
    monkeypatch.setattr(tasks, "create_calendar_sync_task", lambda cid: calls.append(cid) or True)
    resp = client.get("/todos/tree", headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200
    assert calls == [str(cal.todo_id)]  # last_synced_at is None -> stale
```

(Match whatever header/auth style the file's other `client.get`/`client.post` calls already use — `act_as(app)` in `db_setup` may already bypass bearer-token checking entirely; check `tests/helpers.py`'s `act_as` before assuming the `Authorization` header is even required.)

Run: `scripts/test.sh tests/test_calendar_sync.py -v`
Expected: PASS

- [ ] **Step 8: Run the full Python suite**

Run: `scripts/test.sh`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add app/calendar_sync.py app/routes/todos.py requirements.in requirements.txt tests/test_calendar_sync.py
git commit -m "feat: fetch/parse/write calendar sync; nudge staleness on list load

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Digest job also nudges stale calendars

**Files:**
- Modify: `app/push.py` (`run_notify`)
- Test: `tests/test_push_logic.py` or `tests/test_push_api.py` (check which file already tests `run_notify`)

**Interfaces:**
- Consumes: `tasks.enqueue_calendar_sync` (Task 5); `db.get_root_todos`/`db.get_tree` (existing — `run_notify` already reads `db.get_due_todos`, check whether that query would even include `calendar` items, since they have no `due_date` — it likely wouldn't, so this task needs its own read).

- [ ] **Step 1: Find where `run_notify` is tested today**

Run: `grep -rn "run_notify" tests/*.py` and read that test file's fixture setup before writing new tests, so the new test matches its conventions exactly (device registration, `db_setup`-equivalent fixture name may differ from `tests/test_item_types.py`'s).

- [ ] **Step 2: Write the failing test**

In whichever file Step 1 found (call it `tests/test_push_logic.py` unless the grep says otherwise), add:

```python
def test_run_notify_nudges_stale_calendars(monkeypatch):
    # Match this test file's existing setup for a device + a calendar item —
    # copy the device-registration lines from a neighboring test in this file.
    from app import db, models, tasks
    cal = models.Todo(title="Family", type="calendar")
    db.create_todo(cal)
    calls = []
    monkeypatch.setattr(tasks, "create_calendar_sync_task", lambda cid: calls.append(cid) or True)
    push.run_notify(at("2026-02-01T09:00:00+00:00"), send=lambda *a: None)
    assert str(cal.todo_id) in calls
```

- [ ] **Step 3: Run it, confirm it fails**

Run: `scripts/test.sh -k test_run_notify_nudges_stale_calendars`
Expected: FAIL (nothing calls `enqueue_calendar_sync` yet)

- [ ] **Step 4: Implement in `app/push.py`**

`run_notify` currently reads `todos = db.get_due_todos(...)`, which filters to dated todos and would exclude a `calendar` (no `due_date`). Add a separate read for calendars, right after that line:

```python
    calendars = [t for t in db.get_root_todos() if t.type == "calendar"]  # see note below re: nested calendars
```

Note: `get_root_todos` only returns top-level items. If a `calendar` could ever be nested under another item, this would miss it — but per the design, `calendar`s are created at any level like any other type, so use a tree read instead for correctness:

```python
    _, all_todos = db.get_tree()
    calendars = [t for t in all_todos.values() if t.type == "calendar"]
```

Then, right before the existing `tz = tasks.home_tz(devices)` line, add:

```python
    from app import tasks as _tasks_mod  # already imported as tasks at module level? check first
    for cal in calendars:
        tasks.enqueue_calendar_sync(str(cal.todo_id), cal.last_synced_at, now_utc)
```

(Drop the redundant local import if `app.push` already imports `tasks` inside `run_notify`'s existing `from app import db, tasks` line — it does, per the file read earlier in this project: `from app import db, tasks` already appears inside `run_notify`. Just add the loop using that existing `tasks` name, no new import.)

Final diff shape for `run_notify`:

```python
    from app import db, tasks
    send = send or send_fcm
    devices = db.list_push_devices()
    if not devices:
        return {"devices": 0, "sent": 0, "scheduled": 0}
    todos = db.get_due_todos((now_utc + datetime.timedelta(days=2)).replace(tzinfo=None))
    _, all_todos = db.get_tree()
    for cal in all_todos.values():
        if cal.type == "calendar":
            tasks.enqueue_calendar_sync(str(cal.todo_id), cal.last_synced_at, now_utc)
    sent = 0
    for dev in devices:
        ...
```

- [ ] **Step 5: Run the test, confirm it passes**

Run: `scripts/test.sh -k test_run_notify_nudges_stale_calendars`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `scripts/test.sh`
Expected: all PASS (watch specifically for existing `run_notify` tests that assert exact call counts/mocks on `db` — `db.get_tree()` is a new call this function now makes on every digest tick; if a test mocks `db` narrowly it may need updating to allow it)

- [ ] **Step 7: Commit**

```bash
git add app/push.py tests/test_push_logic.py
git commit -m "feat: daily digest also nudges stale calendars

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Client — `calendar_url` edit field

**Files:**
- Modify: `web/fields.js` (`changedFields`)
- Modify: `web/fields-ui.js` (`renderEditFields`)
- Modify: `web/item-form.js` (`FIELD_GROUPS`)
- Test: `tests_js/fields.test.js`, `tests_js/item-form.test.js`

**Interfaces:**
- Consumes: `Types.hasField` (existing, already generalized).
- Produces: `FieldsUI.renderEditFields(todo).groups.calendar_url` (DOM group), folded into `changes().fields.calendar_url` when edited.

- [ ] **Step 1: Write the failing tests**

Add to `tests_js/fields.test.js` (find its existing `changedFields` test and add beside it):

```js
test("changedFields includes calendar_url when it changes", () => {
  const todo = { calendar_url: "https://old.example/f.ics" };
  const next = { calendar_url: "https://new.example/f.ics" };
  assert.deepStrictEqual(Fields.changedFields(todo, next), { calendar_url: "https://new.example/f.ics" });
});

test("changedFields omits calendar_url when unchanged", () => {
  const todo = { calendar_url: "https://same.example/f.ics" };
  const next = { calendar_url: "https://same.example/f.ics" };
  assert.deepStrictEqual(Fields.changedFields(todo, next), {});
});
```

Add to `tests_js/item-form.test.js` (read it first — it's only 962 bytes, likely a single assertion about `FIELD_GROUPS` covering every registry field; match its style):

```js
test("FIELD_GROUPS covers every field calendar/calendar_event declare", () => {
  for (const type of ["calendar", "calendar_event"]) {
    for (const field of TypesData[type].fields) {
      if (field === "title") continue; // title has its own input, not a FIELD_GROUPS entry
      assert.ok(ItemForm.FIELD_GROUPS.includes(field), `${type} field "${field}" has no input`);
    }
  }
});
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `node --test tests_js/fields.test.js tests_js/item-form.test.js`
Expected: FAIL (`calendar_url` not in `changedFields`'s output; `FIELD_GROUPS` missing `calendar_url`/`location`)

- [ ] **Step 3: Implement in `web/fields.js`**

In `changedFields`, add:

```js
    if ((todo.calendar_url ?? null) !== (next.calendar_url ?? null)) out.calendar_url = next.calendar_url ?? null;
```

- [ ] **Step 4: Implement in `web/fields-ui.js`**

Add a URL input renderer near `renderLinksEditor`:

```js
  function renderUrlField(state, key, placeholder) {
    const input = el("input");
    input.type = "url";
    input.inputMode = "url";
    input.placeholder = placeholder;
    input.value = state[key] || "";
    input.autocapitalize = "off";
    input.addEventListener("input", () => { state[key] = input.value; });
    return input;
  }
```

In `renderEditFields`, add `calendar_url` to `state`'s initialization:

```js
    const state = {
      color: Fields.COLORS.includes(todo.color) ? todo.color : null,
      links: (todo.links || []).map((l) => ({ url: l.url, label: l.label || "" })),
      calendar_url: todo.calendar_url || "",
    };
```

And add a group:

```js
    const groups = {
      color: [label("Color"), renderColorPicker(state)],
      links: [label("Links"), renderLinksEditor(state)],
      blocked_by: [label("Blocked by"), renderTodoPicker(todo, blocked, blockerExclusions(todosById, todo))],
      references: [label("References"), renderTodoPicker(todo, refs)],
      calendar_url: [label("Calendar URL"), renderUrlField(state, "calendar_url", "https://…/calendar.ics")],
    };
```

And thread it into `changes()`'s output object:

```js
    function changes() {
      const cleaned = Fields.cleanLinks(state.links);
      if (cleaned.error) return { error: cleaned.error };
      return { fields: Fields.changedFields(base, {
        color: state.color, links: cleaned.links, blocked_by: [...blocked], references: [...refs],
        calendar_url: state.calendar_url.trim() || null,
      }) };
    }
```

Return `renderUrlField` from the module's exports isn't necessary (it's internal to `renderEditFields`); no change to the module's `return { ... }` line needed.

- [ ] **Step 5: Implement in `web/item-form.js`**

Add `calendar_url` and `location` to `FIELD_GROUPS` (order after `due_date`, since a calendar's URL is its most important field once you're editing it):

```js
  const FIELD_GROUPS = ["due_date", "calendar_url", "repeat", "color", "links", "blocked_by", "references", "attachments", "location"];
```

`location` has no editor (it's read-only, populated by sync — `calendar_event` is `editable: false` so its edit sheet is never opened at all; per Task 10 the whole Edit affordance is hidden for that type). `FIELD_GROUPS` just needs the name present so the item-form test in Step 1 passes and nothing crashes if `nodes.location` is looked up — but `nodes` in `item-form.js`'s `render()` won't have a `location` key, so `groups` (built by `FIELD_GROUPS.filter((f) => nodes[f] && ...)`) will simply skip it since `nodes.location` is `undefined`. That's correct: no group renders for a field nobody can reach the edit sheet for anyway. Confirm this by re-reading `render()`'s `groups` construction after this change — no further code needed.

- [ ] **Step 6: Run tests, confirm they pass**

Run: `node --test tests_js/fields.test.js tests_js/item-form.test.js`
Expected: PASS

- [ ] **Step 7: Run the full JS suite**

Run: `node --test tests_js/*.test.js`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add web/fields.js web/fields-ui.js web/item-form.js tests_js/fields.test.js tests_js/item-form.test.js
git commit -m "feat: calendar_url edit field for the calendar type

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 9: Client — read-only `calendar_event` rows, gated Add item, gated drag-in, `location` in viewer

**Files:**
- Modify: `web/render-node.js` (row menu)
- Modify: `web/reorder.js` (`planDrop`)
- Modify: `web/editors.js` (`renderViewer`)
- Test: `tests_js/tree-rules.test.js` or a new `tests_js/calendar-type.test.js`, `tests_js/reorder.test.js`

**Interfaces:**
- Consumes: `Types.can(todo, "editable")`, `Types.can(todo, "allowsUserChildren")` (Task 1, already generated into `web/types-data.js`).

- [ ] **Step 1: Write the failing reorder test**

Read `tests_js/reorder.test.js` first (4.3K, existing `planDrop` tests) to match its model-fixture shape exactly, then add:

```js
test("planDrop refuses to drop inside a type that disallows children", () => {
  const model = {
    roots: [
      { todo_id: "a", parent_id: null, child_ids: [], order_idx: 0, type: "todo" },
      { todo_id: "cal", parent_id: null, child_ids: [], order_idx: 1, type: "calendar" },
    ],
    todosById: new Map(),
  };
  for (const t of model.roots) model.todosById.set(t.todo_id, t);
  assert.strictEqual(Reorder.planDrop(model, "a", "cal", "inside"), null);
});

test("planDrop still allows reordering before/after a no-children type", () => {
  const model = {
    roots: [
      { todo_id: "cal", parent_id: null, child_ids: [], order_idx: 0, type: "calendar" },
      { todo_id: "a", parent_id: null, child_ids: [], order_idx: 1, type: "todo" },
    ],
    todosById: new Map(),
  };
  for (const t of model.roots) model.todosById.set(t.todo_id, t);
  assert.deepStrictEqual(Reorder.planDrop(model, "a", "cal", "before"), { parent_id: null, index: 0 });
});
```

`Reorder` (`web/reorder.js`) is loaded standalone in tests without `Types` available in the same way the browser has it globally — check the top of `reorder.js`: it's a UMD module with no dependency on `Types` today. Task's Step 3 below adds one; make sure the test file's `require`/global setup provides `Types` (check how `tests_js/fields.test.js` — which already depends on `Types` — wires it up, e.g. `global.Types = require("../web/types.js")`, and copy that pattern into `reorder.test.js`'s setup if `reorder.js` needs it after this change).

- [ ] **Step 2: Run it, confirm it fails**

Run: `node --test tests_js/reorder.test.js`
Expected: FAIL (dropping "inside" a calendar currently succeeds)

- [ ] **Step 3: Implement in `web/reorder.js`**

Change the module's factory signature to accept `Types` the way `web/fields.js` does:

```js
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./types.js"));
  } else {
    root.Reorder = factory(root.Types);
  }
})(typeof self !== "undefined" ? self : this, function (Types) {
```

In `planDrop`, in the `zone === "inside"` branch, add the guard first:

```js
    if (zone === "inside") {
      if (!Types.can(target, "allowsUserChildren")) return null;
      const kids = siblingsOf(model, targetId);
      if (kids.length && kids[kids.length - 1] === node) return null;
      return { parent_id: targetId, index: null };
    }
```

Check `index.html`'s script-load order (per the file's own header comment: "classic scripts sharing one global scope, loaded in the order listed in index.html") to confirm `types.js`/`types-data.js` load before `reorder.js`; if not, move `reorder.js`'s `<script>` tag later in `web/index.html`.

- [ ] **Step 4: Run it, confirm it passes**

Run: `node --test tests_js/reorder.test.js`
Expected: PASS

- [ ] **Step 5: Implement the row-menu gating in `web/render-node.js`**

Wrap the existing menu-item appends (around the lines read earlier: `menuItem("Add item", ...)` etc.) in capability checks:

```js
    if (Types.can(todo, "allowsUserChildren")) {
      menu.append(
        menuItem("Add item", "plus", openPanel("add")),
        menuItem("Add several", "split", openPanel("split"))
      );
    }
    if (Types.can(todo, "editable")) {
      menu.append(
        menuItem("Edit", "pencil", openPanel("edit")),
        menuItem(`Type: ${TypeUI.labelOf(Types.nameOf(todo))}`, Types.get(todo).icon, openPanel("type"))
      );
    }

    menu.append(
      menuItem("Copy with subtasks", "copy", () => {
        setActivePanel(null);
        renderTree();
        copyOutline(todo.todo_id);
      })
    );

    if (Types.can(todo, "editable")) {
      menu.append(
        menuItem("Move up", "up", () => reportedFailure(moveTodo(todo.todo_id, "up"))),
        menuItem("Move down", "down", () => reportedFailure(moveTodo(todo.todo_id, "down")))
      );
      menu.append(
        menuItem("Delete", "trash", () => {
          setActivePanel(null);
          reportedFailure(deleteTodo(todo.todo_id));
        }, "todo-menu-item--danger")
      );
    }
```

(This changes the original unconditional five `menu.append(...)` calls into four conditional blocks plus the always-present "Copy with subtasks" — re-read the current block in `web/render-node.js` around line 207-239 before editing, since line numbers will have shifted since this plan was written if earlier tasks touched the same file — they didn't, so it should still match.)

- [ ] **Step 6: Implement `location` + hidden Edit button in `web/editors.js`'s `renderViewer`**

Add a `location` fact, right after the `due_date` fact line:

```js
  if (Types.hasField(todo, "location") && todo.location) fact("Location", todo.location);
```

Change the buttons row to omit Edit when not editable:

```js
  const buttons = DOM.actionBar(
    DOM.sheetButton("Close", "plain", close),
    ...(trashed ? [DOM.sheetButton("Undelete", "primary", trashed.onRestore)]
      : Types.can(todo, "editable") ? [DOM.sheetButton("Edit", "primary", () => {
          setActivePanel("edit", todo.todo_id);
          viewerOrigin = todo.todo_id;
          renderTree();
        })] : [])
  );
```

Check `DOM.actionBar`'s signature (`web/dom.js` or wherever `DOM` lives — it was used elsewhere as `DOM.actionBar(a, b)` with fixed positional args) accepts a variable number of button args via spread; if it takes an explicit array instead of `...args`, adjust the call to `DOM.actionBar(...[btn1, btn2].filter(Boolean))` instead of the array-literal-with-spread shown above — read `web/dom.js` (`function actionBar`) before finalizing this edit.

- [ ] **Step 7: Write a small test for the read-only viewer/menu gating**

Create `tests_js/calendar-type.test.js` (no DOM available under `node --test`, so this only tests the pure logic pieces — `Types.can`/`Types.hasField` on the generated registry data, which is really a Task 1 regression check re-asserted at the client layer):

```js
const test = require("node:test");
const assert = require("node:assert");
const Types = require("../web/types.js");

test("calendar_event is read-only and cannot take user children", () => {
  const ev = { type: "calendar_event" };
  assert.strictEqual(Types.can(ev, "editable"), false);
  assert.strictEqual(Types.can(ev, "allowsUserChildren"), false);
  assert.strictEqual(Types.hasField(ev, "location"), true);
});

test("calendar accepts edits but not manually added children", () => {
  const cal = { type: "calendar" };
  assert.strictEqual(Types.can(cal, "editable"), true);
  assert.strictEqual(Types.can(cal, "allowsUserChildren"), false);
  assert.strictEqual(Types.hasField(cal, "calendar_url"), true);
});
```

- [ ] **Step 8: Run the full JS suite**

Run: `node --test tests_js/*.test.js`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add web/render-node.js web/reorder.js web/editors.js web/index.html tests_js/reorder.test.js tests_js/calendar-type.test.js
git commit -m "feat: read-only calendar_event rows, gated Add item and drag-in

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 10: Client — "Sync now" button and last-synced status in the calendar's own view

**Files:**
- Modify: `web/app.js` (a `syncCalendarNow` action alongside `saveEdit`/`moveTodo`)
- Modify: `web/editors.js` (`renderViewer` — show sync status + button when `todo.type === "calendar"`)
- Test: manual (browser checklist) — this is UI wiring with no pure-logic surface worth a `node --test`; covered by Task 11's browser checklist run

**Interfaces:**
- Consumes: `apiFetch` (existing helper used throughout `app.js` for API calls).

- [ ] **Step 1: Add the action in `web/app.js`**

Near `moveTodo`:

```js
async function syncCalendarNow(todoId) {
  try {
    await apiFetch(`${API_BASE}/${todoId}/sync`, { method: "POST" });
    showNotice({ level: "info", message: "Syncing…" });
  } catch (e) {
    showNotice({ level: "error", message: "Couldn't start sync: " + e.message });
  }
}
```

(Match `apiFetch`'s exact call signature — grep `web/app.js`/`web/sync.js` for another `apiFetch(..., { method: "POST" })` call, e.g. how `deleteTodo`'s engine op eventually calls the API, or a simpler example like `register_push_device`'s client-side caller if one exists in `web/push-client.js`, and copy its error-handling shape exactly rather than inventing a new one.)

- [ ] **Step 2: Show it in the viewer**

In `web/editors.js`'s `renderViewer`, after the `facts` block and before `body.appendChild(FieldsUI.renderDetail(...))`, add:

```js
  if (todo.type === "calendar" && !trashed) {
    const sync = document.createElement("div");
    sync.className = "calendar-sync-status";
    const status = document.createElement("p");
    status.className = "sheet-subtitle";
    status.textContent = todo.last_sync_error
      ? `Last sync failed: ${todo.last_sync_error}`
      : todo.last_synced_at
        ? `Last synced ${Due.format(todo.last_synced_at)}`
        : "Not yet synced";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-plain";
    btn.textContent = "Sync now";
    btn.addEventListener("click", () => syncCalendarNow(todo.todo_id));
    sync.append(status, btn);
    body.appendChild(sync);
  }
```

`Due.format` expects an ISO due-date-shaped string; `last_synced_at` is an ISO datetime too (per Task 1's model), so this should render sensibly, but confirm by checking `Due.format`'s signature in `web/due.js` handles a plain "server instant" string (with trailing `Z`) the same way it handles `due_date` — if it assumes a bare wall-clock string (per `due-time.md`'s note that `due_date` is deliberately bare while `create_date` carries `Z`), use `new Date(todo.last_synced_at).toLocaleString(...)` instead, matching the pattern already used for `trashed.trashed_at` a few lines above in this same function.

- [ ] **Step 3: Add minimal styling**

In `web/style.css`, add a rule near wherever `.sheet-subtitle`/`.btn-plain` are already styled (search for those class names first so this matches, rather than inventing new spacing conventions):

```css
.calendar-sync-status {
  margin-top: 1rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
```

- [ ] **Step 4: Manual smoke check**

Run the app locally (see `docs/okf/ops/local-browser-testing.md`), create a `calendar` item with a real or fixture ICS URL, open its viewer, confirm "Sync now" appears and posting to `/todos/{id}/sync` doesn't error in the console. Full checklist coverage is Task 11.

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/editors.js web/style.css
git commit -m "feat: Sync now button and last-synced status in the calendar viewer

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 11: OKF bundle updates + browser checklist run

**Files:**
- Create: `docs/okf/features/calendar-type.md`
- Modify: `docs/okf/features/item-types.md`
- Modify: `docs/okf/architecture/client-server-split.md`
- Modify: `docs/okf/features/ui-inventory.md`
- Modify: `docs/okf/index.md`
- Modify: `docs/okf/log.md`
- Modify: `docs/okf/ops/local-browser-testing.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: Read the current versions of every file above**

Read each with the file tool immediately before editing (their content isn't known from this plan's research and may have shifted).

- [ ] **Step 2: Write `docs/okf/features/calendar-type.md`**

Follow the frontmatter shape used by `docs/okf/features/item-types.md` (`type: Feature`, `title`, `description`, `resource`, `tags`, `timestamp` set to the actual commit time). Body covers: the two types and their registry flags (`allowsUserChildren`, `editable` — and cross-link `item-types.md` since those flags apply to every type, not just calendar's); the no-cron sync trigger set (list load / manual button / digest, 6h staleness, 60-day window, full-replace-by-`external_uid` reconciliation, failure handling); the Cloud Task reuse of the reminder queue; the enforcement points (`split_todo`/`reparent_todo` 400s, client menu/drag gating); the read-only UI. Link the spec: `docs/superpowers/specs/2026-09-22-calendar-type-design.md`.

- [ ] **Step 3: Update `item-types.md`**

Add a paragraph noting the registry grew two new flags (`allowsUserChildren`, `editable`) and two new types, with a pointer to the new `calendar-type.md` for their specifics; bump `timestamp`.

- [ ] **Step 4: Update `client-server-split.md`**

Under "Server deliberately owns the logic," add:

> **Calendar sync** ([calendar type](../features/calendar-type.md)) — `app/calendar_sync.py` fetches, parses and reconciles server-side: it must run with no client open (the digest-triggered nudge) and reconcile atomically by `external_uid` regardless of which device's page load triggered it.

Bump `timestamp`.

- [ ] **Step 5: Update `ui-inventory.md`**

Add rows for: the calendar's "Sync now" button + last-synced status (viewer), the read-only `calendar_event` row (no checkbox, no swipe-complete, limited `...` menu), and the suppressed "Add item"/"Add several" under a `calendar` row. Match the file's existing row-entry format exactly (re-read it before editing — Task list earlier already showed its `**Row menu ...` line style).

- [ ] **Step 6: Update `index.md` and `log.md`**

Link the new `calendar-type.md` from `index.md` wherever `item-types.md` is linked (same section). Append one dated `log.md` line summarizing the feature and listing every OKF file touched, matching the existing log-line format (see the `2026-09-21: Unified item UI` example read earlier).

- [ ] **Step 7: Run the browser checklist**

Follow `docs/okf/ops/local-browser-testing.md` in Chrome per `CLAUDE.md`'s required rule for any UI change: exercise creating a `calendar`, editing its URL, triggering Sync now, confirming events appear read-only, confirming Add item is absent on a `calendar` row, and run through the rest of the file's existing checklist to confirm nothing else broke (the due-chip/menu changes touch shared rendering code).

- [ ] **Step 8: Commit**

```bash
git add docs/okf/
git commit -m "docs: OKF updates for the calendar item type

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 12: Full verification and deploy

**Files:** none (verification + deploy only)

- [ ] **Step 1: Run the full test suite**

```bash
scripts/test.sh
node --test tests_js/*.test.js
scripts/e2e.sh
```

Expected: all PASS. Fix any regression before proceeding — do not deploy on red tests.

- [ ] **Step 2: Confirm the generated registry file is current**

```bash
python scripts/gen_types.py
git status --short web/types-data.js
```

Expected: no diff (already committed in Task 1; this just guards against drift from any later edit to `app/types.json`).

- [ ] **Step 3: Confirm OKF sync**

```bash
git log --oneline -15
```

Skim for any code commit in this plan that didn't touch `docs/okf/` in the same commit — Task 11 covers the bundle in one commit at the end rather than per-task, which is a deliberate deviation from the usual "same commit as the change" rule (each task in this plan is one deployable slice, but the OKF bundle describes the *finished* feature more naturally as one pass at the end). Note this explicitly when reporting completion, since it's a one-time exception, not a new convention.

- [ ] **Step 4: Deploy**

```bash
./deploy.sh
```

Expected: deploy succeeds, `scripts/cost-check.sh` (run automatically at the end of `deploy.sh`) passes.

- [ ] **Step 5: Announce completion**

Per stored preference: run `say` (e.g. `say "Calendar type is deployed"`) once the deploy and cost check both succeed.
