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


def test_nothing_before_nine_local():
    assert plan("2026-09-19T15:59:00", [todo("a", "2026-09-19")]) == []


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


def test_heads_up_within_the_hour_only():
    # 12:00 LA on the 19th is 19:00 UTC; a 12:45 todo is 45 min away, 13:30 is 90 min away.
    out = plan("2026-09-19T19:00:00", [todo("soon", "2026-09-19T12:45:00"), todo("far", "2026-09-19T13:30:00")],
               sent={"digest:2026-09-19:dev": []})
    assert [p.title for p in out] == ["soon"]
    assert out[0].key == "soon:" + str(out[0].key.split(":")[1]) + ":2026-09-19T12:45:00:dev"


def test_date_only_never_gets_a_heads_up():
    assert plan("2026-09-19T19:00:00", [todo("allday", "2026-09-19")], sent={"digest:2026-09-19:dev": []}) == []


def test_heads_up_not_repeated_once_marked():
    t = todo("soon", "2026-09-19T12:45:00")
    key = f"soon:{t.todo_id}:2026-09-19T12:45:00:dev"
    assert plan("2026-09-19T19:00:00", [t], sent={"digest:2026-09-19:dev": [], key: []}) == []


def test_overnight_window_folds_into_the_digest():
    # Due 09:30 LA: its window opened at 08:30, before the digest hour, and the digest lists it.
    t = todo("early", "2026-09-19T09:30:00")
    out = plan(NINE_LA, [t])
    assert [p.key for p in out] == ["digest:2026-09-19:dev"]


def test_afternoon_todo_in_the_digest_still_gets_its_heads_up():
    t = todo("three", "2026-09-19T15:00:00")
    digest = {"digest:2026-09-19:dev": [str(t.todo_id)]}
    out = plan("2026-09-19T21:30:00", [t], sent=digest)  # 14:30 LA
    assert [p.title for p in out] == ["three"]


def test_timezone_is_respected():
    # The same instant: 09:00 in Los Angeles, 12:00 in New York.
    la = plan(NINE_LA, [todo("a", "2026-09-19")], tz=LA)
    ny = plan(NINE_LA, [todo("a", "2026-09-19")], tz="America/New_York")
    assert la[0].key == ny[0].key == "digest:2026-09-19:dev"
    assert plan("2026-09-19T15:30:00", [todo("a", "2026-09-19")], tz="America/New_York")  # 11:30 NY: after nine
    assert plan("2026-09-19T15:30:00", [todo("a", "2026-09-19")], tz=LA) == []          # 08:30 LA: before nine


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
