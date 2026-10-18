from datetime import date, datetime

from daykeeper.days import Days
from daykeeper.models import Habit, Task
from daykeeper.repo import Repo

SUN, MON = date(2026, 10, 18), date(2026, 10, 19)


def make(db, clock):
    repo = Repo(db)
    calls = []

    def summarize(d):
        calls.append(d)
        return {"day": d.isoformat()}

    return repo, Days(repo, summarize, clock), calls


def test_habits_spawn_on_scheduled_day_once(db, clock):
    repo, days, _ = make(db, clock)
    repo.add_habit(Habit(None, "зарядка", frozenset({0, 1, 2, 3, 4}), tag="sport"))
    days.ensure(SUN)
    assert repo.tasks(SUN) == []
    days.ensure(MON)
    days.ensure(MON)
    tasks = repo.tasks(MON)
    assert [(t.title, t.kind, t.tag) for t in tasks] == [("зарядка", "check", "sport")]
    assert tasks[0].habit_id is not None


def test_habits_go_to_end(db, clock):
    repo, days, _ = make(db, clock)
    repo.insert_task(Task(None, MON, "уже есть", "check"), None)
    repo.add_habit(Habit(None, "зарядка"))
    days.ensure(MON)
    assert [t.title for t in repo.tasks(MON)] == ["уже есть", "зарядка"]


def test_inactive_habit_not_spawned(db, clock):
    repo, days, _ = make(db, clock)
    repo.add_habit(Habit(None, "старое", active=False))
    days.ensure(MON)
    assert repo.tasks(MON) == []


def test_autoclose_previous(db, clock):
    repo, days, calls = make(db, clock)
    repo.insert_task(Task(None, date(2026, 10, 17), "вчера", "check"), None)
    days.ensure(SUN)
    row = repo.day_row(date(2026, 10, 17))
    assert row["closed"] == 1 and row["summary_seen"] == 0
    assert calls == [date(2026, 10, 17)]
    assert days.pending_summary() == (date(2026, 10, 17), {"day": "2026-10-17"})


def test_autoclose_skips_empty_and_closed(db, clock):
    repo, days, calls = make(db, clock)
    repo.insert_task(Task(None, date(2026, 10, 16), "x", "check"), None)
    days.close(date(2026, 10, 16))
    calls.clear()
    days.ensure(SUN)
    assert calls == []
    assert days.pending_summary() is None


def test_close_marks_seen(db, clock):
    repo, days, _ = make(db, clock)
    repo.insert_task(Task(None, SUN, "x", "check"), None)
    assert days.close(SUN) == {"day": "2026-10-18"}
    assert days.pending_summary() is None
    assert repo.day_row(SUN)["closed"] == 1


def test_mark_seen(db, clock):
    repo, days, _ = make(db, clock)
    repo.insert_task(Task(None, date(2026, 10, 17), "x", "check"), None)
    days.ensure(SUN)
    days.mark_seen(date(2026, 10, 17))
    assert days.pending_summary() is None


def test_closed_day_still_editable(db, clock):
    repo, days, _ = make(db, clock)
    t = repo.insert_task(Task(None, SUN, "x", "check"), None)
    days.close(SUN)
    repo.set_done(t.id, True, datetime(2026, 10, 18, 22))
    assert repo.task(t.id).done


def test_mark_seen_covers_older_days(db, clock):
    repo, days, _ = make(db, clock)
    repo.insert_task(Task(None, date(2026, 10, 15), "x", "check"), None)
    repo.insert_task(Task(None, date(2026, 10, 17), "y", "check"), None)
    days.ensure(SUN)
    assert days.pending_summary()[0] == date(2026, 10, 17)
    days.mark_seen(date(2026, 10, 17))
    assert days.pending_summary() is None
