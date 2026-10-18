from datetime import date, datetime, time, timedelta

import pytest

from daykeeper.models import Goal, Habit, Segment, Task, Tracker
from daykeeper.repo import Repo
from daykeeper.stats import Stats, fmt_duration, plural

SUN = date(2026, 10, 18)
WED = date(2026, 10, 14)


@pytest.fixture
def env(db):
    repo = Repo(db)
    return repo, Stats(repo)


def work(repo, day, seconds, tag=None, completed=False, title="w"):
    t = repo.insert_task(Task(None, day, title, "duration", duration_min=60, tag=tag), None)
    start = datetime.combine(day, time(10))
    repo.add_segment(Segment(t.id, day, start, start + timedelta(seconds=seconds), seconds, completed))
    return t


def habit_days(repo, habit, days_done: dict):
    for d, done in days_done.items():
        t = repo.insert_task(Task(None, d, habit.title, "check", habit_id=habit.id), None)
        if done:
            repo.set_done(t.id, True, datetime.combine(d, time(8)))


def test_fmt_and_plural():
    assert fmt_duration(0) == "0м"
    assert fmt_duration(47 * 60) == "47м"
    assert fmt_duration(70 * 60) == "1ч10м"
    assert fmt_duration(2 * 3600) == "2ч"
    assert [plural(n, "день", "дня", "дней") for n in (1, 3, 5, 11, 21)] == ["день", "дня", "дней", "дней", "день"]


def test_focus_includes_partial(env):
    repo, stats = env
    work(repo, SUN, 2400)
    work(repo, SUN, 2820, completed=True)
    assert stats.focus_by_day(SUN, SUN) == {SUN: 5220}
    assert stats.pomodoros(SUN) == 1


def test_focus_range_has_zero_days(env):
    _, stats = env
    assert stats.focus_by_day(WED, WED + timedelta(days=1)) == {WED: 0, WED + timedelta(days=1): 0}


def test_streak_with_gap_and_today_not_done(env):
    repo, stats = env
    h = repo.add_habit(Habit(None, "зарядка"))
    d = [SUN - timedelta(days=i) for i in range(6, -1, -1)]  # 12..18
    habit_days(repo, h, {d[0]: True, d[1]: True, d[2]: True, d[3]: False, d[4]: True, d[5]: True, d[6]: False})
    assert stats.habit_streak(h.id, SUN) == (2, 3)


def test_streak_counts_today_when_done(env):
    repo, stats = env
    h = repo.add_habit(Habit(None, "зарядка"))
    habit_days(repo, h, {SUN - timedelta(days=1): True, SUN: True})
    assert stats.habit_streak(h.id, SUN) == (2, 2)


def test_streak_skips_unscheduled_days(env):
    repo, stats = env
    h = repo.add_habit(Habit(None, "спорт", frozenset({0, 2, 4})))
    habit_days(repo, h, {date(2026, 10, 12): True, date(2026, 10, 14): True, date(2026, 10, 16): True})
    assert stats.habit_streak(h.id, SUN) == (3, 3)


def test_habit_grid(env):
    repo, stats = env
    h = repo.add_habit(Habit(None, "спорт", frozenset({0, 2, 4})))
    habit_days(repo, h, {date(2026, 10, 14): True, date(2026, 10, 16): False})
    grid = stats.habit_grid(h.id, SUN, days=7)
    assert len(grid) == 7
    assert grid == [None, None, True, None, False, None, None]  # 12..18


def test_goal_focus_week_pace(env):
    repo, stats = env
    g = repo.add_goal(Goal(None, "бот", "focus_tag", 20, date(2026, 10, 1), tag="bot", period="week"))
    work(repo, date(2026, 10, 12), 4 * 3600, tag="bot")
    work(repo, WED, 3 * 3600, tag="bot")
    work(repo, WED, 3600, tag="other")
    work(repo, date(2026, 10, 11), 3600, tag="bot")  # previous week
    p = stats.goal_progress(g, WED)
    assert p["value"] == pytest.approx(7)
    assert p["expected"] == pytest.approx(20 * 3 / 7)
    assert p["delta"] == pytest.approx(7 - 20 * 3 / 7)
    assert p["behind"] is True


def test_goal_count_tag(env):
    repo, stats = env
    g = repo.add_goal(Goal(None, "англ", "count_tag", 30, date(2026, 10, 1), tag="eng", deadline=date(2026, 10, 31)))
    for _ in range(3):
        t = repo.insert_task(Task(None, WED, "урок", "check", tag="eng"), None)
        repo.set_done(t.id, True, datetime(2026, 10, 14, 12))
    repo.insert_task(Task(None, WED, "урок", "check", tag="eng"), None)
    p = stats.goal_progress(g, WED)
    assert p["value"] == 3
    assert p["expected"] == pytest.approx(30 * 13 / 30)


def test_goal_tracker_deadline(env):
    repo, stats = env
    tr = repo.add_tracker(Tracker(None, "вес", "кг"))
    g = repo.add_goal(Goal(None, "вес 75", "tracker", 75, date(2026, 10, 1), tracker_id=tr.id, deadline=date(2026, 12, 1)))
    repo.log_tracker(tr.id, date(2026, 10, 1), 80)
    repo.log_tracker(tr.id, WED, 79)
    p = stats.goal_progress(g, WED)
    assert p["value"] == 79 and p["start"] == 80
    frac = 13 / 61
    assert p["expected"] == pytest.approx(80 + (75 - 80) * frac)
    assert p["behind"] is (79 > 80 + (75 - 80) * frac)


def test_goal_without_pace(env):
    repo, stats = env
    g = repo.add_goal(Goal(None, "бот", "focus_tag", 100, date(2026, 10, 1), tag="bot"))
    p = stats.goal_progress(g, WED)
    assert p["expected"] is None and p["behind"] is False


def test_motivation_empty(env):
    assert env[1].motivation(SUN) is None


def test_motivation_best_week(env):
    repo, stats = env
    for weeks_ago, hours in [(1, 3), (2, 4), (3, 2)]:
        work(repo, WED - timedelta(weeks=weeks_ago), hours * 3600)
    work(repo, WED, 5 * 3600)
    assert stats.motivation(SUN) == "лучшая неделя по фокусу за месяц"


def test_motivation_streak_near_record(env):
    repo, stats = env
    h = repo.add_habit(Habit(None, "зарядка"))
    start = SUN - timedelta(days=30)
    habit_days(repo, h, {start + timedelta(days=i): True for i in range(5)})  # record 5
    habit_days(repo, h, {start + timedelta(days=5): False})
    habit_days(repo, h, {SUN - timedelta(days=i): True for i in range(3, -1, -1)})  # current 4
    assert stats.motivation(SUN) == "зарядка — 4 дня подряд, рекорд 5"


def test_motivation_streak_record(env):
    repo, stats = env
    h = repo.add_habit(Habit(None, "зарядка"))
    habit_days(repo, h, {SUN - timedelta(days=i): True for i in range(2, -1, -1)})
    assert stats.motivation(SUN) == "зарядка — 3 дня подряд, новый рекорд"


def test_motivation_more_than_yesterday(env):
    repo, stats = env
    work(repo, SUN - timedelta(days=1), 3600)
    work(repo, SUN, 3600 + 40 * 60)
    assert stats.motivation(SUN) == "сегодня на 40м больше фокуса, чем вчера"


def test_day_summary(env):
    repo, stats = env
    h = repo.add_habit(Habit(None, "зарядка"))
    habit_days(repo, h, {SUN: True})
    work(repo, SUN, 2820, completed=True, title="бот")
    repo.insert_task(Task(None, SUN, "чтение", "check"), None)
    s = stats.day_summary(SUN)
    assert s["done"] == ["зарядка"]
    assert s["not_done"] == ["бот", "чтение"]
    assert (s["focus_s"], s["pomodoros"]) == (2820, 1)
    assert s["habits"] == [{"title": "зарядка", "done": True, "streak": 1}]
    assert set(s) >= {"goals", "motivation", "day"}


def test_dashboard_shape(env):
    repo, stats = env
    repo.insert_task(Task(None, SUN, "вечер", "timed", start=time(19), end=time(20)), None)
    tr = repo.add_tracker(Tracker(None, "сон", "ч"))
    repo.log_tracker(tr.id, SUN, 7.5)
    d = stats.dashboard(datetime(2026, 10, 18, 12))
    assert d["today"]["next_timed"] == {"title": "вечер", "start": "19:00"}
    assert len(d["week"]["days"]) == 7 and d["week"]["days"][0]["day"] == "2026-10-12"
    assert d["trackers"][0]["last"] == 7.5 and len(d["trackers"][0]["series"]) == 7
    assert d["motivation"] is None
