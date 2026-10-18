from datetime import date, datetime, time

import pytest

from daykeeper.models import Goal, Habit, Phase, Segment, Task, TimerState, Tracker
from daykeeper.ordering import OrderError
from daykeeper.repo import Repo

D = date(2026, 10, 18)


def T(title, kind="check", **kw):
    return Task(None, D, title, kind, **kw)


def titles(r, d=D):
    return [x.title for x in r.tasks(d)]


def test_insert_respects_order(db):
    r = Repo(db)
    r.insert_task(T("работа", "timed", start=time(19), end=time(20)), None)
    r.insert_task(T("утро", "timed", start=time(9), end=time(10)), None)
    r.insert_task(T("зубы"), None)
    assert titles(r) == ["утро", "работа", "зубы"]
    assert [x.position for x in r.tasks(D)] == [0, 1, 2]


def test_insert_explicit_index(db):
    r = Repo(db)
    r.insert_task(T("a"), None)
    r.insert_task(T("b"), None)
    r.insert_task(T("c"), 1)
    assert titles(r) == ["a", "c", "b"]


def test_insert_explicit_index_violating(db):
    r = Repo(db)
    r.insert_task(T("утро", "timed", start=time(9), end=time(10)), None)
    with pytest.raises(OrderError):
        r.insert_task(T("вечер", "timed", start=time(19), end=time(20)), 0)
    assert titles(r) == ["утро"]


def test_roundtrip_fields(db):
    r = Repo(db)
    t = r.insert_task(T("w", "duration", duration_min=120, tag="bot"), None)
    got = r.task(t.id)
    assert (got.kind, got.duration_min, got.tag, got.done, got.day) == ("duration", 120, "bot", False, D)


def test_task_missing(db):
    with pytest.raises(KeyError):
        Repo(db).task(999)


@pytest.mark.parametrize("bad", [
    T("  "),
    T("x", "timed", start=time(10), end=time(9)),
    T("x", "timed", start=time(10)),
    T("x", "duration"),
    T("x", "duration", duration_min=0),
])
def test_validation(db, bad):
    with pytest.raises(ValueError):
        Repo(db).insert_task(bad, None)


def test_move_invalid_keeps_db(db):
    r = Repo(db)
    r.insert_task(T("утро", "timed", start=time(9), end=time(10)), None)
    r.insert_task(T("зубы"), None)
    evening = r.insert_task(T("вечер", "timed", start=time(19), end=time(20)), None)
    with pytest.raises(OrderError):
        r.move_task(evening.id, 0)
    assert titles(r) == ["утро", "зубы", "вечер"]


def test_move_free(db):
    r = Repo(db)
    a = r.insert_task(T("a"), None)
    r.insert_task(T("b"), None)
    r.move_task(a.id, 1)
    assert titles(r) == ["b", "a"]


def test_update_time_settles(db):
    r = Repo(db)
    r.insert_task(T("утро", "timed", start=time(9), end=time(10)), None)
    r.insert_task(T("зубы"), None)
    evening = r.insert_task(T("вечер", "timed", start=time(19), end=time(20)), None)
    r.update_task(evening.id, start=time(8), end=time(8, 30))
    assert titles(r) == ["вечер", "утро", "зубы"]


def test_update_validates(db):
    r = Repo(db)
    t = r.insert_task(T("a"), None)
    with pytest.raises(ValueError):
        r.update_task(t.id, title="")
    assert r.task(t.id).title == "a"


def test_delete_compacts_positions(db):
    r = Repo(db)
    a = r.insert_task(T("a"), None)
    r.insert_task(T("b"), None)
    r.delete_task(a.id)
    assert [(x.title, x.position) for x in r.tasks(D)] == [("b", 0)]


def test_set_done_and_progress(db):
    r = Repo(db)
    t = r.insert_task(T("a", "duration", duration_min=60), None)
    at = datetime(2026, 10, 18, 12)
    r.set_done(t.id, True, at)
    r.save_progress(t.id, 1, 300)
    got = r.task(t.id)
    assert (got.done, got.done_at, got.progress_phase, got.progress_elapsed_s) == (True, at, 1, 300)
    r.set_done(t.id, False, at)
    assert r.task(t.id).done_at is None


def test_habits_crud(db):
    r = Repo(db)
    h = r.add_habit(Habit(None, "зарядка", frozenset({0, 2, 4}), tag="sport"))
    assert r.habits()[0].weekdays == frozenset({0, 2, 4})
    r.update_habit(h.id, active=False)
    assert r.habits(active_only=True) == []
    r.delete_habit(h.id)
    assert r.habits() == []


def test_tracker_log_upsert(db):
    r = Repo(db)
    tr = r.add_tracker(Tracker(None, "вес", "кг"))
    r.log_tracker(tr.id, D, 78.4)
    r.log_tracker(tr.id, D, 78.1)
    assert r.tracker_entries(tr.id) == [(D, 78.1)]
    assert r.tracker_by_name("вес").id == tr.id


def test_goals_crud(db):
    r = Repo(db)
    g = r.add_goal(Goal(None, "бот 20ч", "focus_tag", 20, D, tag="bot", period="week"))
    assert r.goals()[0].period == "week"
    r.update_goal(g.id, target=25)
    assert r.goal(g.id).target == 25
    r.delete_goal(g.id)
    assert r.goals() == []


def test_segments_range(db):
    r = Repo(db)
    t = r.insert_task(T("a", "duration", duration_min=60), None)
    s = Segment(t.id, D, datetime(2026, 10, 18, 9), datetime(2026, 10, 18, 9, 47), 2820, True)
    r.add_segment(s)
    assert r.segments(D, D) == [s]
    assert r.segments(date(2026, 10, 19), date(2026, 10, 20)) == []


def test_day_rows(db):
    r = Repo(db)
    assert r.day_row(D) is None
    r.upsert_day(D, spawned=1)
    r.upsert_day(D, closed=1, summary_json="{}")
    row = r.day_row(D)
    assert (row["spawned"], row["closed"], row["summary_json"]) == (1, 1, "{}")


def test_timer_roundtrip(db):
    r = Repo(db)
    st = TimerState(5, [Phase("work", 47), Phase("break", 13)], 1, 30, True, datetime(2026, 10, 18, 10))
    r.save_timer(st)
    assert r.load_timer() == st
    r.save_timer(None)
    assert r.load_timer() is None


def test_move_to_other_day_keeps_id_and_segments(db):
    r = Repo(db)
    a = r.insert_task(T("a", "duration", duration_min=60, tag="bot"), None)
    r.insert_task(T("b"), None)
    r.add_segment(Segment(a.id, D, datetime(2026, 10, 18, 9), datetime(2026, 10, 18, 9, 10), 600, False))
    tomorrow = date(2026, 10, 19)
    r.insert_task(Task(None, tomorrow, "утро", "timed", start=time(9), end=time(10)), None)
    moved = r.update_task(a.id, day=tomorrow)
    assert moved.id == a.id and moved.day == tomorrow
    assert [t.title for t in r.tasks(tomorrow)] == ["утро", "a"]
    assert [(t.title, t.position) for t in r.tasks(D)] == [("b", 0)]
    assert r.segments(D, D)[0].task_id == a.id
