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


def mk(title, due=None, done=False, order=None, kids=(), blocked_by=(), deleted=False,
       type="todo", priority="normal"):
    t = models.Todo(title=title, due_date=due, done=done, order_idx=order, type=type,
                    priority=priority, blocked_by=[b.todo_id for b in blocked_by], deleted=deleted)
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


# ---- calendar events: they don't consume the limit --------------------------

_TODAY = datetime.date(2026, 9, 20)


def event(title, due):
    return mk(title, due, type="calendar_event")


def test_events_due_today_are_added_on_top_of_a_full_todo_list():
    todos = [mk(f"t{i}", d(21)) for i in range(10)]
    stand_up, lunch = event("stand-up", at(20, 9)), event("lunch", at(20, 12))
    out = rank(*todos, stand_up, lunch, limit=10, today=_TODAY)
    assert titles(out) == ["stand-up", "lunch", *[f"t{i}" for i in range(10)]]


def test_overdue_events_are_added_even_when_todos_already_pass_the_limit():
    todos = [mk(f"due{i}", d(10)) for i in range(12)]
    yesterday = event("yesterday", d(19))
    out = rank(*todos, yesterday, limit=10, today=_TODAY)
    assert titles(out) == ["due0", "due1", "due2", "due3", "due4", "due5", "due6",
                           "due7", "due8", "due9", "due10", "due11", "yesterday"]


def test_future_events_fill_only_the_slots_left_under_the_limit():
    todos = [mk("a", d(21)), mk("b", d(22)), mk("c", d(23))]
    events = [event(f"e{i}", d(24 + i)) for i in range(5)]
    assert titles(rank(*todos, *events, limit=5, today=_TODAY)) == ["a", "b", "c", "e0", "e1"]


def test_future_events_stop_once_today_events_already_reach_the_limit():
    todos = [mk(f"t{i}", d(21)) for i in range(8)]
    today_events = [event(f"now{i}", at(20, 9 + i)) for i in range(3)]
    later = [event(f"later{i}", d(25 + i)) for i in range(4)]
    out = rank(*todos, *today_events, *later, limit=10, today=_TODAY)
    assert titles(out) == ["now0", "now1", "now2", *[f"t{i}" for i in range(8)]]


def test_without_today_events_only_fill_leftover_slots():
    todos = [mk(f"t{i}", d(21)) for i in range(10)]
    meet = event("meet", d(20))
    assert titles(rank(*todos, meet, limit=10)) == [f"t{i}" for i in range(10)]
    short = [mk("a", d(21)), mk("b", d(22))]
    fillers = [event(f"e{i}", d(23 + i)) for i in range(4)]
    assert titles(rank(*short, *fillers, limit=4)) == ["a", "b", "e0", "e1"]


def test_an_event_keeps_its_place_by_due_date_among_the_todos():
    undated, later, meet = mk("undated"), mk("later", d(25)), event("meet", at(20, 9))
    assert titles(rank(undated, later, meet, today=_TODAY)) == ["meet", "later", "undated"]


def test_inserting_an_event_does_not_reorder_a_blocker():
    blocker = mk("blocker")
    blocked = mk("blocked", d(10), blocked_by=[blocker])
    meet = event("meet", at(10, 9))
    assert titles(rank(blocked, blocker, meet, today=datetime.date(2026, 9, 10))) == [
        "meet", "blocker", "blocked"]


# ---- priority: high first, then normal, low only fills what's left ----------

def test_high_priority_ranks_ahead_of_an_earlier_normal():
    later, sooner = mk("later", priority="high"), mk("sooner", d(10))
    assert titles(rank(sooner, later)) == ["later", "sooner"]


def test_high_items_sort_by_due_date_among_themselves():
    later, sooner = mk("later", d(20), priority="high"), mk("sooner", d(10), priority="high")
    assert titles(rank(later, sooner)) == ["sooner", "later"]


def test_high_does_not_displace_a_normal_due_today():
    high = mk("high", d(25), priority="high")
    dues = [mk(f"due{i}", d(10)) for i in range(2)]
    assert titles(rank(high, *dues, limit=2, today=datetime.date(2026, 9, 20))) == [
        "high", "due0", "due1"]


def test_low_is_left_out_while_normals_fill_the_limit():
    normal = [mk(f"n{i}", d(21 + i)) for i in range(3)]
    low = mk("low", d(1), priority="low")
    assert titles(rank(low, *normal, limit=3, today=_TODAY)) == ["n0", "n1", "n2"]


def test_low_fills_leftover_slots_soonest_first():
    normal = mk("normal", d(21))
    lows = [mk("l2", d(24), priority="low"), mk("l0", d(22), priority="low"),
            mk("l1", d(23), priority="low")]
    assert titles(rank(normal, *lows, limit=3, today=_TODAY)) == ["normal", "l0", "l1"]


def test_a_high_event_not_due_yet_is_still_included():
    todos = [mk(f"t{i}", d(21)) for i in range(10)]
    later = mk("later", d(28), type="calendar_event", priority="high")
    assert titles(rank(*todos, later, limit=10, today=_TODAY)) == [
        "later", *[f"t{i}" for i in range(10)]]


def test_a_low_event_due_today_does_not_force_itself_in():
    todos = [mk(f"t{i}", d(21)) for i in range(10)]
    meet = mk("today", at(20, 9), type="calendar_event", priority="low")
    assert titles(rank(*todos, meet, limit=10, today=_TODAY)) == [f"t{i}" for i in range(10)]


def test_a_low_blocker_of_a_shown_item_is_still_pulled_up():
    blocker = mk("blocker", priority="low")
    blocked = mk("blocked", d(1), blocked_by=[blocker])
    fillers = [mk(f"f{i}", d(2 + i)) for i in range(12)]
    out = rank(blocked, *fillers, blocker, limit=3)
    assert titles(out)[:2] == ["blocker", "blocked"]
