import datetime as dt
from app import models, push

UTC = dt.timezone.utc
LA = "America/Los_Angeles"


def todo(title, due, done=False):
    return models.Todo(title=title, due_date=dt.datetime.fromisoformat(due) if due else None, done=done)


def at(iso_utc):
    return dt.datetime.fromisoformat(iso_utc).replace(tzinfo=UTC)


def plan(now_utc, todos, tz=LA, sent=None):
    sent = sent or {}
    return push.plan_device("dev", tz, at(now_utc), todos, sent.get)


# 2026-09-19 16:00 UTC is 09:00 in Los Angeles (PDT, UTC-7).
NINE_LA = "2026-09-19T16:00:00"


def test_digest_lists_today_and_overdue_with_count():
    todos = [todo("today", "2026-09-19"), todo("late", "2026-09-17T10:00:00"),
             todo("later", "2026-09-20"), todo("done", "2026-09-19", done=True), todo("none", None)]
    out = plan(NINE_LA, todos)
    assert len(out) == 1 and not out[0].silent
    assert out[0].title == "2 due today"
    assert out[0].body == "late, today"
    assert out[0].key == "digest:2026-09-19:dev"


def test_digest_truncates_long_lists():
    todos = [todo(f"t{i}", "2026-09-19") for i in range(5)]
    assert plan(NINE_LA, todos)[0].body.endswith("+2 more")


def test_digest_is_marker_only_when_nothing_due():
    out = plan(NINE_LA, [todo("later", "2026-09-25")])
    assert len(out) == 1 and out[0].silent


def test_no_second_digest_when_marker_exists():
    assert plan(NINE_LA, [todo("a", "2026-09-19")], sent={"digest:2026-09-19:dev": ["x"]}) == []


def test_timezone_is_respected():
    # The same instant: 09:00 in Los Angeles, 12:00 in New York.
    la = plan(NINE_LA, [todo("a", "2026-09-19")], tz=LA)
    ny = plan(NINE_LA, [todo("a", "2026-09-19")], tz="America/New_York")
    assert la[0].key == ny[0].key == "digest:2026-09-19:dev"
    # 02:00 UTC on the 20th is still the 19th in LA but already the 20th in Tokyo.
    late = "2026-09-20T02:00:00"
    assert plan(late, [todo("a", "2026-09-19")], tz=LA)[0].key == "digest:2026-09-19:dev"
    assert plan(late, [todo("a", "2026-09-19")], tz="Asia/Tokyo")[0].key == "digest:2026-09-20:dev"


def test_no_hour_gate_and_no_heads_up():
    # A manual or retried tick at any hour still sends the day's digest; timed todos get nothing extra.
    out = plan("2026-09-19T15:59:00", [todo("t", "2026-09-19T15:00:00")])
    assert [p.key for p in out] == ["digest:2026-09-19:dev"]


def test_bad_timezone_falls_back_to_utc():
    assert plan("2026-09-19T09:00:00", [todo("a", "2026-09-19")], tz="Not/AZone")[0].title == "1 due today"


def test_offset_aware_due_is_converted_to_the_device_zone():
    # 2026-09-19T23:00Z is 16:00 in LA: due today there.
    out = plan(NINE_LA, [todo("aware", "2026-09-19T23:00:00+00:00")])
    assert out[0].title == "1 due today"


def test_deleted_todos_are_ignored():
    t = todo("gone", "2026-09-19")
    t.deleted = True
    assert plan(NINE_LA, [t])[0].silent


def test_device_id_is_stable_and_short():
    assert push.device_id("abc") == push.device_id("abc") != push.device_id("abd")
    assert len(push.device_id("abc")) == 32


def test_valid_tz():
    assert push.valid_tz(LA) and not push.valid_tz("Nope/Nope") and not push.valid_tz("")
