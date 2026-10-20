"""The facade every client goes through. JSON-compatible in and out; Russian error texts."""

import inspect
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, time

from .config import Config
from .days import Days
from .models import Goal, Habit, Task, Tracker
from .ordering import OrderError
from .pomodoro import pomodoro_count
from .quickadd import parse_quick_add
from .repo import Repo
from .stats import Stats
from .timer import Event, Timer, TimerError


class ServiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


READ_ONLY = {
    "day_get", "timer_status", "day_summary", "summary_pending", "habit_list", "goal_list",
    "tracker_list", "stats_range", "dashboard", "history",
}


def _date(v) -> date | None:
    if v is None or isinstance(v, date):
        return v
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"неверная дата: {v} (нужно ГГГГ-ММ-ДД)")


def _time(v) -> time | None:
    if v is None or isinstance(v, time):
        return v
    try:
        return time.fromisoformat(v)
    except ValueError:
        raise ValueError(f"неверное время: {v} (нужно ЧЧ:ММ)")


def _hm(t: time | None) -> str | None:
    return f"{t:%H:%M}" if t else None


class Service:
    METHODS: tuple[str, ...] = (
        "day_get", "task_add", "task_quick_add", "task_update", "task_delete", "task_move", "task_done",
        "timer_start", "timer_pause", "timer_resume", "timer_toggle", "timer_skip", "timer_stop", "timer_status",
        "day_close", "day_summary", "summary_pending", "summary_seen",
        "habit_add", "habit_update", "habit_delete", "habit_list",
        "goal_add", "goal_update", "goal_delete", "goal_list",
        "tracker_add", "tracker_delete", "tracker_list", "tracker_log",
        "stats_range", "dashboard", "history",
    )

    def __init__(self, con: sqlite3.Connection, cfg: Config, clock: Callable[[], datetime]):
        self.cfg = cfg
        self.clock = clock
        self.repo = Repo(con)
        self.stats = Stats(self.repo)
        self.days = Days(self.repo, self.stats.day_summary, clock)
        self.timer = Timer(self.repo, cfg, clock)
        self.on_event: Callable[[list[Event]], None] = lambda events: None
        self.on_change: Callable[[], None] = lambda: None
        self.version = 0
        self._last_day = self.today()

    # --- dispatch --------------------------------------------------------

    def call(self, method: str, **params):
        if method not in self.METHODS:
            raise ServiceError("unknown_method", f"нет такой операции: {method}")
        fn = getattr(self, method)
        try:
            inspect.signature(fn).bind(**params)
        except TypeError as e:
            raise ServiceError("invalid", f"неверные параметры: {e}")
        try:
            self.days.ensure(self.today())
            result = fn(**params)
        except ServiceError:
            raise
        except KeyError:
            raise ServiceError("not_found", "задачи нет" if method.startswith(("task_", "timer_")) else "не найдено")
        except (OrderError, TimerError, ValueError) as e:
            raise ServiceError("invalid", str(e))
        if method not in READ_ONLY:
            self._changed()
        return result

    def _changed(self) -> None:
        self.version += 1
        self.on_change()

    def today(self) -> date:
        return self.clock().date()

    def _day(self, day) -> date:
        return _date(day) or self.today()

    def _emit(self, events: list[Event]) -> list[Event]:
        if events:
            self.on_event(events)
        return events

    def tick(self) -> list[Event]:
        changed = False
        today = self.today()
        if today != self._last_day:
            self._last_day = today
            self.days.ensure(today)
            changed = True
        events = self.timer.tick()
        if events:
            self._emit(events)
            changed = True
        if changed:
            self._changed()
        return events

    # --- views -----------------------------------------------------------

    def _task_view(self, t: Task) -> dict:
        planned = t.planned_min
        running = self.timer.state is not None and self.timer.state.task_id == t.id
        return {
            "id": t.id, "title": t.title, "kind": t.kind, "start": _hm(t.start), "end": _hm(t.end),
            "duration_min": t.duration_min,
            "pomodoros": pomodoro_count(planned, self.cfg.work_min, self.cfg.break_min) if planned else None,
            "tag": t.tag, "done": t.done, "running": running,
        }

    # --- days & tasks ----------------------------------------------------

    def day_get(self, day=None) -> dict:
        d = self._day(day)
        self.days.ensure(d)
        tasks = self.repo.tasks(d)
        row = self.repo.day_row(d) or {}
        return {
            "day": d.isoformat(), "closed": bool(row.get("closed")),
            "done": sum(t.done for t in tasks), "total": len(tasks),
            "focus_s": self.stats.focus_total(d, d),
            "tasks": [self._task_view(t) for t in tasks],
        }

    def task_add(self, title, kind, day=None, start=None, end=None, duration_min=None, tag=None, index=None) -> dict:
        d = self._day(day)
        self.days.ensure(d)
        task = Task(None, d, title, kind, start=_time(start), end=_time(end),
                    duration_min=int(duration_min) if duration_min is not None else None, tag=tag)
        return self._task_view(self.repo.insert_task(task, index))

    def task_quick_add(self, text, day=None) -> dict:
        p = parse_quick_add(text)
        return self.task_add(p["title"], p["kind"], day=day, start=p["start"], end=p["end"], duration_min=p["duration_min"])

    def task_update(self, task_id, **fields) -> dict:
        if "start" in fields:
            fields["start"] = _time(fields["start"])
        if "end" in fields:
            fields["end"] = _time(fields["end"])
        if "day" in fields:
            fields["day"] = _date(fields["day"])
        reshapes = {"kind", "start", "end", "duration_min", "day"} & set(fields)
        if reshapes and self.timer.state and self.timer.state.task_id == task_id:
            self.repo.task(task_id)
            self.timer.stop()
            if reshapes - {"day"}:
                self.repo.save_progress(task_id, 0, 0)
        return self._task_view(self.repo.update_task(task_id, **fields))

    def task_delete(self, task_id) -> None:
        if self.timer.state and self.timer.state.task_id == task_id:
            self.timer.stop()
        self.repo.delete_task(task_id)

    def task_move(self, task_id, index) -> dict:
        task = self.repo.task(task_id)
        self.repo.move_task(task_id, int(index))
        return self.day_get(task.day.isoformat())

    def task_done(self, task_id, done=True) -> dict:
        task = self.repo.task(task_id)
        if done and task.done:
            raise ServiceError("already", "уже сделано")
        if done and self.timer.state and self.timer.state.task_id == task_id:
            self.timer.stop()
        self.repo.set_done(task_id, bool(done), self.clock())
        return self._task_view(self.repo.task(task_id))

    # --- timer -----------------------------------------------------------

    def timer_start(self, task_id) -> dict | None:
        self._emit(self.timer.start(task_id))
        return self.timer_status()

    def timer_pause(self):
        self.timer.pause()
        return self.timer_status()

    def timer_resume(self):
        self.timer.resume()
        return self.timer_status()

    def timer_toggle(self):
        self.timer.toggle()
        return self.timer_status()

    def timer_skip(self):
        self._emit(self.timer.skip())
        return self.timer_status()

    def timer_stop(self):
        self.timer.stop()
        return None

    def timer_status(self) -> dict | None:
        st = self.timer.state
        if st is None:
            return None
        task = self.repo.task(st.task_id)
        phase = st.phases[st.phase_index]
        works = [i for i, p in enumerate(st.phases) if p.kind == "work"]
        done_or_current = [i for i in works if i <= st.phase_index]
        return {
            "task_id": st.task_id, "title": task.title, "phase": phase.kind,
            "pomodoro_no": max(1, len(done_or_current)), "pomodoro_total": len(works),
            "remaining_s": self.timer.remaining_s(), "phase_s": phase.minutes * 60,
            "running": st.running,
            "next": [{"kind": p.kind, "minutes": p.minutes} for p in st.phases[st.phase_index + 1:]],
        }

    # --- day lifecycle ---------------------------------------------------

    def day_close(self, day=None) -> dict:
        return self.days.close(self._day(day))

    def day_summary(self, day=None) -> dict:
        return self.stats.day_summary(self._day(day))

    def summary_pending(self) -> dict | None:
        pending = self.days.pending_summary()
        if pending is None:
            return None
        d, summary = pending
        return {"day": d.isoformat(), "summary": summary}

    def summary_seen(self, day) -> None:
        self.days.mark_seen(_date(day))

    # --- habits ----------------------------------------------------------

    @staticmethod
    def _habit_view(h: Habit) -> dict:
        return {"id": h.id, "title": h.title, "weekdays": sorted(h.weekdays), "tag": h.tag, "active": h.active}

    def habit_add(self, title, weekdays=None, tag=None) -> dict:
        wd = frozenset(int(x) for x in weekdays) if weekdays is not None else frozenset(range(7))
        habit = self.repo.add_habit(Habit(None, title, wd, tag))
        self.days.spawn_habit(habit)
        return self._habit_view(habit)

    def habit_update(self, habit_id, **fields) -> dict:
        if "weekdays" in fields:
            fields["weekdays"] = frozenset(int(x) for x in fields["weekdays"])
        return self._habit_view(self.repo.update_habit(habit_id, **fields))

    def habit_delete(self, habit_id) -> None:
        self.repo.delete_habit(habit_id)

    def habit_list(self) -> list[dict]:
        today = self.today()
        out = []
        for h in self.repo.habits():
            current, best = self.stats.habit_streak(h.id, today)
            out.append(self._habit_view(h) | {"streak": current, "best": best})
        return out

    # --- goals -----------------------------------------------------------

    def goal_add(self, title, kind, target, tag=None, tracker=None, period=None, deadline=None) -> dict:
        if kind not in ("focus_tag", "tracker", "count_tag"):
            raise ValueError("вид цели: focus_tag, tracker или count_tag")
        if kind == "tracker" and not tracker:
            raise ValueError("для цели по трекеру нужен трекер")
        if kind != "tracker" and not tag:
            raise ValueError("для этой цели нужен тег задач")
        if period not in (None, "week"):
            raise ValueError("период: week или без периода")
        tracker_id = self.repo.tracker_by_name(tracker).id if tracker else None
        goal = Goal(None, title, kind, float(target), self.today(), tag=tag, tracker_id=tracker_id,
                    period=period, deadline=_date(deadline))
        return self.stats.goal_progress(self.repo.add_goal(goal), self.today())

    def goal_update(self, goal_id, **fields) -> dict:
        if "deadline" in fields:
            fields["deadline"] = _date(fields["deadline"])
        return self.stats.goal_progress(self.repo.update_goal(goal_id, **fields), self.today())

    def goal_delete(self, goal_id) -> None:
        self.repo.delete_goal(goal_id)

    def goal_list(self) -> list[dict]:
        return [self.stats.goal_progress(g, self.today()) for g in self.repo.goals()]

    # --- trackers --------------------------------------------------------

    def tracker_add(self, name, unit=None) -> dict:
        t = self.repo.add_tracker(Tracker(None, name, unit))
        return {"id": t.id, "name": t.name, "unit": t.unit}

    def tracker_delete(self, tracker_id) -> None:
        self.repo.delete_tracker(tracker_id)

    def tracker_list(self) -> list[dict]:
        return [self.stats._tracker_view(t, self.today()) for t in self.repo.trackers()]

    def tracker_log(self, tracker, value, day=None) -> None:
        self.repo.log_tracker(self.repo.tracker_by_name(tracker).id, self._day(day), float(value))

    # --- stats -----------------------------------------------------------

    def stats_range(self, start, end) -> dict:
        by_day = self.stats.focus_by_day(_date(start), _date(end))
        return {"focus_by_day": {d.isoformat(): s for d, s in by_day.items()}, "total_s": sum(by_day.values())}

    def dashboard(self, day=None) -> dict:
        now = self.clock()
        if day is not None:
            now = datetime.combine(_date(day), now.time())
        return self.stats.dashboard(now)

    def history(self, start, end) -> list[dict]:
        s, e = _date(start), _date(end)
        days = sorted({t.day for t in self.repo.tasks_between(s, e)})
        return [self.stats.day_summary(d) for d in days]

    # --- live state for subscribers --------------------------------------

    def live_state(self) -> dict:
        today = self.today()
        tasks = self.repo.tasks(today)
        now = self.clock().time().replace(second=0, microsecond=0)
        upcoming = [t for t in tasks if t.kind == "timed" and not t.done and t.start >= now]
        return {
            "today": today.isoformat(),
            "version": self.version,
            "timer": self.timer_status(),
            "day": {
                "done": sum(t.done for t in tasks), "total": len(tasks),
                "next_timed": {"title": upcoming[0].title, "start": _hm(upcoming[0].start)} if upcoming else None,
            },
        }



