"""Calendar feed: app/ics.py rendering, the secret-URL gate, and the signed-in link route."""
import datetime
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import auth, db, ics, models
from app.main import app

STAMP = datetime.datetime(2026, 9, 20, 12, 0, 0)
TOKEN = "a" * 48


def mk(title, due=None, done=False, deleted=False, parent=None, version=1):
    t = models.Todo(title=title, due_date=due, done=done, deleted=deleted, version=version)
    if parent is not None:
        t.parent_id = parent.todo_id
    return t


def feed(*todos):
    return ics.build_calendar({str(t.todo_id): t for t in todos}, STAMP)


def test_all_day_and_timed_events():
    a = mk("Pay rent", datetime.datetime(2026, 9, 25))
    b = mk("Call Sam", datetime.datetime(2026, 9, 25, 15, 30), version=3)
    out = feed(b, a)
    assert out.startswith("BEGIN:VCALENDAR\r\n") and out.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20260925\r\nDTEND;VALUE=DATE:20260926" in out
    assert "DTSTART:20260925T153000\r\nDTEND:20260925T160000" in out  # floating, 30 min
    assert f"UID:{a.todo_id}@now" in out and "SEQUENCE:3" in out and "DTSTAMP:20260920T120000Z" in out
    assert out.index("Pay rent") < out.index("Call Sam")  # sorted by due date, all-day first
    assert out.count("BEGIN:VEVENT") == 2 and out.count("TRANSP:TRANSPARENT") == 2


def test_month_end_all_day_rolls_over():
    assert "DTEND;VALUE=DATE:20261001" in feed(mk("x", datetime.datetime(2026, 9, 30)))


def test_skips_done_deleted_and_undated():
    out = feed(mk("open", datetime.datetime(2026, 9, 25)), mk("done", datetime.datetime(2026, 9, 25), done=True),
               mk("gone", datetime.datetime(2026, 9, 25), deleted=True), mk("nodate"))
    assert out.count("BEGIN:VEVENT") == 1 and "SUMMARY:open" in out


def test_subtask_names_its_parent():
    p = mk("Trip")
    c = mk("Book flights", datetime.datetime(2026, 9, 25), parent=p)
    assert "DESCRIPTION:Subtask of: Trip" in feed(p, c)


def test_text_escaping_and_folding():
    out = feed(mk("a, b; c\\d\nline2", datetime.datetime(2026, 9, 25)))
    assert "SUMMARY:a\\, b\; c\\\\d\\nline2" in out
    long = feed(mk("é" * 80, datetime.datetime(2026, 9, 25)))
    for line in long.split("\r\n"):
        assert len(line.encode()) <= 75
    unfolded = long.replace("\r\n ", "")
    assert "SUMMARY:" + "é" * 80 in unfolded  # no character split by folding


def test_empty_feed_is_valid():
    out = feed()
    assert "BEGIN:VEVENT" not in out and out.startswith("BEGIN:VCALENDAR")


def _req(path, method="GET", authorization=None):
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""})


def test_token_unlocks_only_the_feed(monkeypatch):
    monkeypatch.setattr(auth, "CALENDAR_TOKEN", TOKEN)
    auth.require_user(_req(f"/calendar/{TOKEN}.ics"))
    for bad in (_req(f"/calendar/{'b' * 48}.ics"), _req(f"/calendar/{TOKEN}.ics", method="POST"),
                _req(f"/calendar/{TOKEN}"), _req(f"/todos/root"), _req("/calendar/link")):
        with pytest.raises(HTTPException) as e:
            auth.require_user(bad)
        assert e.value.status_code == 401


def test_feed_off_when_unset(monkeypatch):
    monkeypatch.setattr(auth, "CALENDAR_TOKEN", "")
    with pytest.raises(HTTPException):
        auth.require_user(_req("/calendar/.ics"))
    with pytest.raises(HTTPException):
        auth.require_user(_req(f"/calendar/{TOKEN}.ics"))


@pytest.fixture
def client():
    app.dependency_overrides[auth.require_user] = lambda: None
    db.init()
    for name in ("todos", "todos_archive", "txn_log", "meta"):
        for doc in db.get_conn().collection(name).stream():
            doc.reference.delete()
    yield TestClient(app)
    db.teardown()


def test_feed_route_serves_calendar(client):
    client.post("/todos", json={"title": "Dentist", "due_date": "2026-09-25T09:00:00"})
    client.post("/todos", json={"title": "no date"})
    r = client.get(f"/calendar/{TOKEN}.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Dentist" in r.text and "no date" not in r.text
    assert "private" in r.headers["cache-control"]


def test_link_route(client, monkeypatch):
    monkeypatch.setattr(auth, "CALENDAR_TOKEN", TOKEN)
    assert client.get("/calendar/link").json() == {"enabled": True, "path": f"/calendar/{TOKEN}.ics"}
    monkeypatch.setattr(auth, "CALENDAR_TOKEN", "")
    assert client.get("/calendar/link").json() == {"enabled": False, "path": None}
    monkeypatch.setattr(auth, "CALENDAR_TOKEN", "short")  # not a usable path segment
    assert client.get("/calendar/link").json()["enabled"] is False
