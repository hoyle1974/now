"""Ranking rules for the Next up view (app/next_up.py) and its endpoint."""
import datetime

from fastapi.testclient import TestClient

from app import db, models
from app.main import app
from app.next_up import rank_next_up
from tests.helpers import act_as, wipe_users


def d(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 9, day)


_ALL: dict[str, models.Todo] = {}


def mk(title, due=None, done=False, order=None, kids=(), blocked_by=(), deleted=False):
    t = models.Todo(title=title, due_date=due, done=done, order_idx=order,
                    blocked_by=[b.todo_id for b in blocked_by], deleted=deleted)
    t.child_ids = [k.todo_id for k in kids]
    for k in kids:
        k.parent_id = t.todo_id
    _ALL[str(t.todo_id)] = t
    return t


def rank(*roots, limit=10, today=None):
    return rank_next_up(list(roots), _ALL, limit, today)


def titles(items):
    return [i["title"] for i in items]


def test_earlier_due_first_then_undated_in_list_order():
    a, b, c, e = mk("later", d(20)), mk("undated 1"), mk("sooner", d(10)), mk("undated 2")
    assert titles(rank(a, b, c, e)) == ["sooner", "later", "undated 1", "undated 2"]


def test_subtasks_inherit_parent_due_date():
    parent = mk("trip", d(25), kids=[mk("flights", order=0), mk("hotel", order=1)])
    soon = mk("soon", d(20))
    out = rank(parent, soon)
    assert titles(out) == ["soon", "flights", "hotel"]
    assert out[1]["due_source"] == "parent"
    assert out[1]["effective_due"] == d(25)
    assert out[1]["path"] == ["trip"]


def test_own_earlier_date_beats_parent_date():
    parent = mk("trip", d(25), kids=[mk("plain", order=0), mk("urgent", d(12), order=1)])
    out = rank(parent)
    assert titles(out) == ["urgent", "plain"]
    assert out[0]["due_source"] == "self"


def test_parent_is_skipped_while_it_has_open_children_but_counts_when_finished():
    parent = mk("p", d(20), kids=[mk("open child", order=0), mk("done child", done=True, order=1)])
    assert titles(rank(parent)) == ["open child"]
    finished = mk("q", d(20), kids=[mk("all done", done=True)])
    assert titles(rank(finished)) == ["q"]


def test_done_roots_and_their_subtrees_are_left_out():
    assert rank(mk("x", done=True, kids=[mk("y")])) == []


def test_children_follow_order_idx_and_limit_applies():
    parent = mk("p", kids=[mk("second", order=1), mk("first", order=0)])
    assert titles(rank(parent)) == ["first", "second"]
    many = [mk(f"t{i}", d(1 + i)) for i in range(15)]
    out = rank(*many, limit=10)
    assert len(out) == 10 and out[0]["rank"] == 1 and out[-1]["rank"] == 10


def test_endpoint_returns_ranked_items():
    act_as(app)
    client = TestClient(app)
    db.init()
    wipe_users()
    client.post("/todos", json={"title": "undated"})
    client.post("/todos", json={"title": "due", "due_date": "2026-09-10"})
    response = client.get("/todos/next")
    assert response.status_code == 200
    assert [i["title"] for i in response.json()["items"]] == ["due", "undated"]
    assert client.get("/todos/next?limit=1").json()["items"][0]["title"] == "due"
    db.teardown()


def at(day: int, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 9, day, hour, minute)


def test_same_day_earlier_time_ranks_first_and_all_day_counts_as_end_of_day():
    late, early, all_day = mk("late", at(10, 17)), mk("early", at(10, 9, 30)), mk("all day", d(10))
    assert titles(rank(late, all_day, early)) == ["early", "late", "all day"]


def test_a_timed_due_still_sorts_by_date_before_time():
    tomorrow_morning, today_evening = mk("tomorrow am", at(11, 8)), mk("today pm", at(10, 22))
    assert titles(rank(tomorrow_morning, today_evening)) == ["today pm", "tomorrow am"]


# ---- blocked_by: a blocker is pulled up to just above what it blocks ----------

def test_blocker_is_pulled_up_above_the_todo_it_blocks():
    blocker = mk("blocker")                      # undated, would rank last
    blocked = mk("blocked", d(10), blocked_by=[blocker])
    other = mk("other", d(12))
    assert titles(rank(blocked, other, blocker)) == ["blocker", "blocked", "other"]


def test_unrelated_todos_keep_their_order():
    blocker = mk("blocker")
    blocked = mk("blocked", d(10), blocked_by=[blocker])
    a, b = mk("a", d(5)), mk("b", d(20))
    assert titles(rank(a, blocked, b, blocker)) == ["a", "blocker", "blocked", "b"]


def test_blocker_already_above_stays_put():
    blocker = mk("blocker", d(5))
    blocked = mk("blocked", d(10), blocked_by=[blocker])
    assert titles(rank(blocked, blocker)) == ["blocker", "blocked"]


def test_chain_of_blockers_is_ordered_end_to_end():
    c = mk("c")
    b = mk("b", blocked_by=[c])
    a = mk("a", d(10), blocked_by=[b])
    assert titles(rank(a, b, c)) == ["c", "b", "a"]


def test_all_open_leaves_of_a_blocker_go_above():
    parent = mk("blocker parent", kids=[mk("step 1", order=0), mk("step 2", order=1)])
    blocked = mk("blocked", d(10), blocked_by=[parent])
    assert titles(rank(blocked, parent)) == ["step 1", "step 2", "blocked"]


def test_done_or_deleted_blocker_is_ignored():
    done_b = mk("done blocker", done=True)
    gone_b = mk("gone blocker", deleted=True)
    blocked = mk("blocked", d(10), blocked_by=[done_b, gone_b])
    other = mk("other", d(12))
    assert titles(rank(blocked, other)) == ["blocked", "other"]


def test_a_blocked_parent_blocks_its_subtasks():
    blocker = mk("blocker")
    parent = mk("trip", d(10), kids=[mk("flights", order=0)], blocked_by=[blocker])
    assert titles(rank(parent, blocker)) == ["blocker", "flights"]


def test_blocker_is_never_cut_off_below_the_limit():
    blocker = mk("blocker")
    blocked = mk("blocked", d(1), blocked_by=[blocker])
    fillers = [mk(f"f{i}", d(2 + i)) for i in range(12)]
    out = rank(blocked, *fillers, blocker, limit=3)
    assert titles(out)[:2] == ["blocker", "blocked"] and [i["rank"] for i in out] == [1, 2, 3]


def test_cycles_do_not_hang():
    a, b = mk("a", d(10)), mk("b", d(11))
    a.blocked_by = [b.todo_id]
    b.blocked_by = [a.todo_id]
    assert sorted(titles(rank(a, b))) == ["a", "b"]


def test_items_name_their_open_blockers():
    blocker, done_b = mk("Get quote"), mk("old", done=True)
    blocked = mk("Book job", blocked_by=[blocker, done_b])
    out = rank(blocked, blocker)
    assert out[0]["blocked_by"] == [] and out[1]["blocked_by"] == ["Get quote"]


def test_all_due_today_or_overdue_shown_beyond_limit():
    todos = [mk(f"due{i}", d(10)) for i in range(4)] + [mk("later", d(25)), mk("undated")]
    assert [i["title"] for i in rank(*todos, limit=2, today=datetime.date(2026, 9, 20))] == [
        "due0", "due1", "due2", "due3"]


def test_fills_to_limit_with_next_most_urgent():
    todos = [mk("due", d(20)), mk("a", d(22)), mk("b", d(23)), mk("undated")]
    titles = [i["title"] for i in rank(*todos, limit=3, today=datetime.date(2026, 9, 20))]
    assert titles == ["due", "a", "b"]
