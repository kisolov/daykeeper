from datetime import date, datetime

import pytest

from daykeeper.config import Config
from daykeeper.service import Service, ServiceError


@pytest.fixture
def svc(db, clock):
    return Service(db, Config(), clock)


def test_methods_registry_complete():
    expected = {
        "day_get", "task_add", "task_quick_add", "task_update", "task_delete", "task_move", "task_done",
        "timer_start", "timer_pause", "timer_resume", "timer_toggle", "timer_skip", "timer_stop", "timer_status",
        "day_close", "day_summary", "summary_pending", "summary_seen",
        "habit_add", "habit_update", "habit_delete", "habit_list",
        "goal_add", "goal_update", "goal_delete", "goal_list",
        "tracker_add", "tracker_delete", "tracker_list", "tracker_log",
        "stats_range", "dashboard", "history",
    }
    assert expected <= set(Service.METHODS)


def test_quick_add_bad_input(svc):
    with pytest.raises(ServiceError) as e:
        svc.call("task_quick_add", text="10:00-09:00 x")
    assert e.value.code == "invalid" and "конец раньше начала" in e.value.message
    assert svc.call("day_get")["tasks"] == []


def test_day_get_shape(svc):
    svc.call("task_add", title="тренировка", kind="duration", duration_min=120, tag="sport")
    svc.call("task_add", title="утро", kind="timed", start="09:00", end="10:00")
    day = svc.call("day_get")
    assert set(day) == {"day", "closed", "done", "total", "focus_s", "tasks"}
    assert day["day"] == "2026-10-18" and day["total"] == 2
    first, second = day["tasks"]
    assert set(first) == {"id", "title", "kind", "start", "end", "duration_min", "pomodoros", "tag", "done", "running"}
    assert (first["title"], first["start"], first["pomodoros"]) == ("тренировка", None, 2)
    assert (second["title"], second["start"], second["pomodoros"]) == ("утро", "09:00", 1)


def test_move_violation_message(svc):
    svc.call("task_add", title="утро", kind="timed", start="09:00", end="10:00")
    ev = svc.call("task_add", title="вечер", kind="timed", start="19:00", end="20:00")
    with pytest.raises(ServiceError, match="не может стоять выше"):
        svc.call("task_move", task_id=ev["id"], index=0)


def test_not_found(svc):
    with pytest.raises(ServiceError) as e:
        svc.call("task_done", task_id=999)
    assert e.value.code == "not_found" and e.value.message == "задачи нет"


def test_done_twice(svc):
    t = svc.call("task_quick_add", text="зубы")
    svc.call("task_done", task_id=t["id"])
    with pytest.raises(ServiceError) as e:
        svc.call("task_done", task_id=t["id"])
    assert e.value.code == "already" and e.value.message == "уже сделано"


def test_done_stops_running_timer(svc):
    t = svc.call("task_quick_add", text="код 1ч")
    svc.call("timer_start", task_id=t["id"])
    svc.call("task_done", task_id=t["id"])
    assert svc.call("timer_status") is None


def test_timer_status_shape(svc, clock):
    t = svc.call("task_quick_add", text="код 2ч")
    svc.call("timer_start", task_id=t["id"])
    clock.advance(60)
    st = svc.call("timer_status")
    assert st["title"] == "код" and st["phase"] == "work" and st["running"] is True
    assert (st["pomodoro_no"], st["pomodoro_total"], st["remaining_s"], st["phase_s"]) == (1, 2, 46 * 60, 47 * 60)
    assert st["next"] == [{"kind": "break", "minutes": 13}, {"kind": "work", "minutes": 47}, {"kind": "break", "minutes": 13}]


def test_unknown_method(svc):
    with pytest.raises(ServiceError) as e:
        svc.call("rm_rf")
    assert e.value.code == "unknown_method"


def test_bad_params(svc):
    with pytest.raises(ServiceError) as e:
        svc.call("task_add", nope=1)
    assert e.value.code == "invalid"


def test_events_emitted(svc, clock):
    got = []
    svc.on_event = got.extend
    t = svc.call("task_quick_add", text="код 1ч")
    svc.call("timer_start", task_id=t["id"])
    for _ in range(47 * 60 // 5):
        clock.advance(5)
        svc.tick()
    assert any(type(e).__name__ == "TaskCompleted" for e in got)


def test_change_listener(svc):
    calls = []
    svc.on_change = lambda: calls.append(1)
    svc.call("task_quick_add", text="зубы")
    svc.call("day_get")
    assert calls == [1]


def test_habits_goals_trackers(svc):
    svc.call("habit_add", title="зарядка", weekdays=[0, 1, 2, 3, 4, 5, 6], tag="sport")
    assert [t["title"] for t in svc.call("day_get")["tasks"]] == ["зарядка"]
    assert svc.call("day_get", day="2026-10-19")["tasks"][0]["title"] == "зарядка"
    svc.call("tracker_add", name="вес", unit="кг")
    svc.call("tracker_log", tracker="вес", value=78.4)
    g = svc.call("goal_add", title="вес 75", kind="tracker", target=75, tracker="вес", deadline="2026-12-01")
    assert svc.call("goal_list")[0]["value"] == 78.4
    svc.call("goal_delete", goal_id=g["id"])
    assert svc.call("goal_list") == []
    with pytest.raises(ServiceError):
        svc.call("tracker_log", tracker="нет такого", value=1)


def test_close_and_pending(svc, clock):
    svc.call("task_quick_add", text="зубы")
    clock.set(datetime(2026, 10, 19, 9))
    pending = svc.call("summary_pending")
    assert pending["day"] == "2026-10-18" and pending["summary"]["not_done"] == ["зубы"]
    svc.call("summary_seen", day="2026-10-18")
    assert svc.call("summary_pending") is None
    s = svc.call("day_close")
    assert s["day"] == "2026-10-19"


def test_stats_range_and_history(svc):
    svc.call("task_quick_add", text="зубы")
    r = svc.call("stats_range", start="2026-10-12", end="2026-10-18")
    assert r["total_s"] == 0 and len(r["focus_by_day"]) == 7
    h = svc.call("history", start="2026-10-18", end="2026-10-18")
    assert h[0]["not_done"] == ["зубы"]


def test_dashboard_for_other_week(svc):
    d = svc.call("dashboard", day="2026-10-08")
    assert d["week"]["start"] == "2026-10-05"
    assert svc.call("dashboard")["week"]["start"] == "2026-10-12"


def test_move_paused_task_to_tomorrow_keeps_work(svc, clock):
    t = svc.call("task_quick_add", text="код 1ч")
    svc.call("task_quick_add", text="зубы")  # make the moved task not the highest id
    svc.call("timer_start", task_id=t["id"])
    clock.advance(600)
    svc.call("timer_pause")
    moved = svc.call("task_update", task_id=t["id"], day="2026-10-19")
    assert moved["id"] == t["id"]
    assert svc.call("timer_status") is None
    assert svc.call("stats_range", start="2026-10-18", end="2026-10-19")["total_s"] == 600
    svc.tick()
    svc.live_state()


def test_shortening_running_task_stops_timer(svc, clock):
    t = svc.call("task_quick_add", text="код 1ч")
    svc.call("timer_start", task_id=t["id"])
    clock.advance(60)
    svc.call("task_update", task_id=t["id"], duration_min=30)
    assert svc.call("timer_status") is None
    svc.call("timer_start", task_id=t["id"])
    assert svc.call("timer_status")["remaining_s"] <= 30 * 60


def test_retitle_running_task_keeps_timer(svc):
    t = svc.call("task_quick_add", text="код 1ч")
    svc.call("timer_start", task_id=t["id"])
    svc.call("task_update", task_id=t["id"], title="код бота")
    assert svc.call("timer_status")["title"] == "код бота"


def test_tick_spawns_habits_at_midnight(svc, clock):
    svc.call("habit_add", title="зарядка")
    clock.set(datetime(2026, 10, 19, 0, 0, 5))
    svc.tick()
    assert [t.title for t in svc.repo.tasks(date(2026, 10, 19))] == ["зарядка"]
    assert svc.live_state()["today"] == "2026-10-19"


def test_live_state_version_bumps_on_change(svc):
    v0 = svc.live_state()["version"]
    svc.call("task_quick_add", text="зубы")
    assert svc.live_state()["version"] > v0
    svc.call("day_get")
    assert svc.live_state()["version"] == v0 + 1


def test_new_habit_joins_days_already_planned(svc):
    """A habit added later still shows up today and in future days that already exist — not in the past."""
    svc.call("task_quick_add", text="вчера", day="2026-10-17")
    svc.call("day_get")  # today (2026-10-18, Sunday) spawned with no habits yet
    svc.call("task_quick_add", text="пары", day="2026-10-19")
    svc.call("task_quick_add", text="суббота", day="2026-10-24")
    svc.call("habit_add", title="порядок")
    svc.call("habit_add", title="только будни", weekdays=[0, 1, 2, 3, 4])

    titles = lambda d: [t["title"] for t in svc.call("day_get", day=d)["tasks"]]  # noqa: E731
    assert titles("2026-10-18") == ["порядок"]
    assert titles("2026-10-19") == ["пары", "порядок", "только будни"]
    assert titles("2026-10-24") == ["суббота", "порядок"]
    assert titles("2026-10-17") == ["вчера"]


def test_habit_removed_for_a_day_stays_removed(svc):
    svc.call("habit_add", title="порядок")
    task = svc.call("day_get")["tasks"][0]
    svc.call("task_delete", task_id=task["id"])
    svc.call("habit_add", title="рутина")
    assert [t["title"] for t in svc.call("day_get")["tasks"]] == ["рутина"]
