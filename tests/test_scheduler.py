from datetime import date, datetime, time

from daykeeper.models import Phase, Task
from daykeeper.scheduler import describe_events, due_reminders, reminder_text
from daykeeper.timer import PhaseEnded, TaskCompleted

D = date(2026, 10, 18)


def timed(id, h, done=False, day=D):
    return Task(id, day, f"t{id}", "timed", start=time(h), end=time(h + 1), done=done)


def test_due_inside_window():
    got = due_reminders([timed(1, 9)], datetime(2026, 10, 18, 8, 59, 30), datetime(2026, 10, 18, 9, 0, 1))
    assert [t.id for t in got] == [1]


def test_not_due_when_done():
    assert due_reminders([timed(1, 9, done=True)], datetime(2026, 10, 18, 8, 59), datetime(2026, 10, 18, 9, 1)) == []


def test_not_due_twice():
    assert due_reminders([timed(1, 9)], datetime(2026, 10, 18, 9, 0, 0), datetime(2026, 10, 18, 9, 0, 1)) == []


def test_other_day_not_due():
    task = timed(1, 9, day=date(2026, 10, 19))
    assert due_reminders([task], datetime(2026, 10, 18, 8, 59), datetime(2026, 10, 18, 9, 1)) == []


def test_free_tasks_never_due():
    free = Task(2, D, "x", "duration", duration_min=60)
    assert due_reminders([free], datetime(2026, 10, 18, 0), datetime(2026, 10, 18, 23)) == []


def test_reminder_text():
    assert reminder_text(timed(1, 9)) == ("пора: t1", "09:00–10:00")


def test_describe_work_to_break():
    events = [PhaseEnded(1, Phase("work", 47), Phase("break", 13))]
    assert describe_events(events, lambda i: "код") == [("перерыв 13м", "код")]


def test_describe_break_to_work():
    events = [PhaseEnded(1, Phase("break", 13), Phase("work", 47))]
    assert describe_events(events, lambda i: "код") == [("снова работа: код", "47м")]


def test_describe_completed():
    events = [PhaseEnded(1, Phase("work", 47), Phase("break", 13)), TaskCompleted(1)]
    assert describe_events(events, lambda i: "код") == [("готово: код", "отдых 13м")]


def test_describe_completed_no_break():
    events = [PhaseEnded(1, Phase("work", 30), None), TaskCompleted(1)]
    assert describe_events(events, lambda i: "код") == [("готово: код", "")]


def test_describe_last_break_end():
    assert describe_events([PhaseEnded(1, Phase("break", 13), None)], lambda i: "код") == [("отдых закончился", "код")]
