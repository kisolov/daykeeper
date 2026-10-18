"""SQL CRUD. The only module that talks to the tables."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime, time

from . import ordering
from .models import Goal, Habit, Phase, Segment, Task, TimerState, Tracker

_TASK_FIELDS = {"title", "kind", "start", "end", "duration_min", "tag", "habit_id"}


def _d(v):
    return date.fromisoformat(v) if v else None


def _t(v):
    return time.fromisoformat(v) if v else None


def _dt(v):
    return datetime.fromisoformat(v) if v else None


def _iso(v):
    return v.isoformat() if v is not None else None


def validate_task(task: Task) -> None:
    if not task.title or not task.title.strip():
        raise ValueError("у задачи нет названия")
    if task.kind == "timed":
        if task.start is None or task.end is None:
            raise ValueError("у задачи по времени нужны начало и конец")
        if task.end <= task.start:
            raise ValueError("конец раньше начала")
    elif task.kind == "duration":
        if not task.duration_min or task.duration_min <= 0:
            raise ValueError("длительность должна быть больше нуля")
    elif task.kind != "check":
        raise ValueError(f"неизвестный вид задачи: {task.kind}")


def _task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"], day=_d(row["day"]), title=row["title"], kind=row["kind"],
        position=row["position"], start=_t(row["start"]), end=_t(row["end"]),
        duration_min=row["duration_min"], tag=row["tag"], habit_id=row["habit_id"],
        done=bool(row["done"]), done_at=_dt(row["done_at"]),
        progress_phase=row["progress_phase"], progress_elapsed_s=row["progress_elapsed_s"],
    )


def _habit(row) -> Habit:
    return Habit(row["id"], row["title"], frozenset(json.loads(row["weekdays"])), row["tag"], bool(row["active"]))


def _goal(row) -> Goal:
    return Goal(
        id=row["id"], title=row["title"], kind=row["kind"], target=row["target"],
        created=_d(row["created"]), tag=row["tag"], tracker_id=row["tracker_id"],
        period=row["period"], deadline=_d(row["deadline"]),
    )


class Repo:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    # --- tasks -----------------------------------------------------------

    def tasks(self, day: date) -> list[Task]:
        rows = self.con.execute("SELECT * FROM tasks WHERE day=? ORDER BY position", (day.isoformat(),))
        return [_task(r) for r in rows]

    def tasks_between(self, start: date, end: date) -> list[Task]:
        rows = self.con.execute(
            "SELECT * FROM tasks WHERE day BETWEEN ? AND ? ORDER BY day, position",
            (start.isoformat(), end.isoformat()),
        )
        return [_task(r) for r in rows]

    def task(self, task_id: int) -> Task:
        row = self.con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return _task(row)

    def _write_order(self, tasks: list[Task]) -> None:
        self.con.executemany(
            "UPDATE tasks SET position=? WHERE id=?", [(i, t.id) for i, t in enumerate(tasks)]
        )

    def insert_task(self, task: Task, index: int | None) -> Task:
        validate_task(task)
        existing = self.tasks(task.day)
        if index is None:
            index = ordering.insert_index(existing, task)
        index = max(0, min(index, len(existing)))
        candidate = existing[:index] + [replace(task, id=-1)] + existing[index:]
        ordering.move(candidate, -1, index)  # raises OrderError when invalid
        with self.con:
            cur = self.con.execute(
                'INSERT INTO tasks (day, title, kind, position, start, "end", duration_min, tag, habit_id)'
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (task.day.isoformat(), task.title.strip(), task.kind, index, _iso(task.start),
                 _iso(task.end), task.duration_min, task.tag, task.habit_id),
            )
            new_id = cur.lastrowid
            candidate[index] = replace(task, id=new_id)
            self._write_order(candidate)
        return self.task(new_id)

    def update_task(self, task_id: int, **changes) -> Task:
        unknown = set(changes) - _TASK_FIELDS - {"day"}
        if unknown:
            raise ValueError(f"нельзя менять поля: {', '.join(sorted(unknown))}")
        old = self.task(task_id)
        new = replace(old, **changes)
        if new.kind != "timed":
            new = replace(new, start=None, end=None)
        if new.kind != "duration":
            new = replace(new, duration_min=None)
        validate_task(new)
        if new.day != old.day:
            target = self.tasks(new.day)
            index = ordering.insert_index(target, new)
            new_order = target[:index] + [new] + target[index:]
            old_order = [t for t in self.tasks(old.day) if t.id != task_id]
        else:
            new_order = ordering.settle([new if t.id == task_id else t for t in self.tasks(old.day)], task_id)
            old_order = None
        with self.con:
            self.con.execute(
                'UPDATE tasks SET day=?, title=?, kind=?, start=?, "end"=?, duration_min=?, tag=?, habit_id=? WHERE id=?',
                (new.day.isoformat(), new.title.strip(), new.kind, _iso(new.start), _iso(new.end),
                 new.duration_min, new.tag, new.habit_id, task_id),
            )
            self._write_order(new_order)
            if old_order is not None:
                self._write_order(old_order)
        return self.task(task_id)

    def delete_task(self, task_id: int) -> None:
        task = self.task(task_id)
        with self.con:
            self.con.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            self._write_order(self.tasks(task.day))

    def move_task(self, task_id: int, index: int) -> list[Task]:
        task = self.task(task_id)
        result = ordering.move(self.tasks(task.day), task_id, index)
        with self.con:
            self._write_order(result)
        return self.tasks(task.day)

    def set_done(self, task_id: int, done: bool, at: datetime) -> None:
        self.task(task_id)
        with self.con:
            self.con.execute(
                "UPDATE tasks SET done=?, done_at=? WHERE id=?",
                (int(done), _iso(at) if done else None, task_id),
            )

    def save_progress(self, task_id: int, phase: int, elapsed_s: int) -> None:
        with self.con:
            self.con.execute(
                "UPDATE tasks SET progress_phase=?, progress_elapsed_s=? WHERE id=?",
                (phase, elapsed_s, task_id),
            )

    # --- habits ----------------------------------------------------------

    def add_habit(self, habit: Habit) -> Habit:
        if not habit.title.strip():
            raise ValueError("у привычки нет названия")
        if not habit.weekdays or not habit.weekdays <= set(range(7)):
            raise ValueError("дни недели — числа 0 (пн) … 6 (вс)")
        with self.con:
            cur = self.con.execute(
                "INSERT INTO habits (title, weekdays, tag, active) VALUES (?,?,?,?)",
                (habit.title.strip(), json.dumps(sorted(habit.weekdays)), habit.tag, int(habit.active)),
            )
        return self.habit(cur.lastrowid)

    def habit(self, habit_id: int) -> Habit:
        row = self.con.execute("SELECT * FROM habits WHERE id=?", (habit_id,)).fetchone()
        if row is None:
            raise KeyError(habit_id)
        return _habit(row)

    def habits(self, active_only: bool = False) -> list[Habit]:
        sql = "SELECT * FROM habits" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
        return [_habit(r) for r in self.con.execute(sql)]

    def update_habit(self, habit_id: int, **changes) -> Habit:
        h = replace(self.habit(habit_id), **changes)
        with self.con:
            self.con.execute(
                "UPDATE habits SET title=?, weekdays=?, tag=?, active=? WHERE id=?",
                (h.title, json.dumps(sorted(h.weekdays)), h.tag, int(h.active), habit_id),
            )
        return self.habit(habit_id)

    def delete_habit(self, habit_id: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM habits WHERE id=?", (habit_id,))

    # --- trackers --------------------------------------------------------

    def add_tracker(self, tracker: Tracker) -> Tracker:
        if not tracker.name.strip():
            raise ValueError("у трекера нет названия")
        with self.con:
            cur = self.con.execute(
                "INSERT INTO trackers (name, unit) VALUES (?,?)", (tracker.name.strip(), tracker.unit)
            )
        return Tracker(cur.lastrowid, tracker.name.strip(), tracker.unit)

    def trackers(self) -> list[Tracker]:
        return [Tracker(r["id"], r["name"], r["unit"]) for r in self.con.execute("SELECT * FROM trackers ORDER BY id")]

    def tracker_by_name(self, name: str) -> Tracker:
        row = self.con.execute("SELECT * FROM trackers WHERE name=?", (name,)).fetchone()
        if row is None:
            raise KeyError(name)
        return Tracker(row["id"], row["name"], row["unit"])

    def delete_tracker(self, tracker_id: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM trackers WHERE id=?", (tracker_id,))

    def log_tracker(self, tracker_id: int, day: date, value: float) -> None:
        with self.con:
            self.con.execute(
                "INSERT INTO tracker_entries (tracker_id, day, value) VALUES (?,?,?)"
                " ON CONFLICT (tracker_id, day) DO UPDATE SET value=excluded.value",
                (tracker_id, day.isoformat(), value),
            )

    def tracker_entries(self, tracker_id: int, start: date | None = None, end: date | None = None) -> list[tuple[date, float]]:
        rows = self.con.execute(
            "SELECT day, value FROM tracker_entries WHERE tracker_id=? AND day BETWEEN ? AND ? ORDER BY day",
            (tracker_id, (start or date.min).isoformat(), (end or date.max).isoformat()),
        )
        return [(_d(r["day"]), r["value"]) for r in rows]

    # --- goals -----------------------------------------------------------

    def add_goal(self, goal: Goal) -> Goal:
        if not goal.title.strip():
            raise ValueError("у цели нет названия")
        with self.con:
            cur = self.con.execute(
                "INSERT INTO goals (title, kind, target, created, tag, tracker_id, period, deadline)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (goal.title.strip(), goal.kind, goal.target, goal.created.isoformat(), goal.tag,
                 goal.tracker_id, goal.period, _iso(goal.deadline)),
            )
        return self.goal(cur.lastrowid)

    def goal(self, goal_id: int) -> Goal:
        row = self.con.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        if row is None:
            raise KeyError(goal_id)
        return _goal(row)

    def goals(self) -> list[Goal]:
        return [_goal(r) for r in self.con.execute("SELECT * FROM goals ORDER BY id")]

    def update_goal(self, goal_id: int, **changes) -> Goal:
        g = replace(self.goal(goal_id), **changes)
        with self.con:
            self.con.execute(
                "UPDATE goals SET title=?, kind=?, target=?, tag=?, tracker_id=?, period=?, deadline=? WHERE id=?",
                (g.title, g.kind, g.target, g.tag, g.tracker_id, g.period, _iso(g.deadline), goal_id),
            )
        return self.goal(goal_id)

    def delete_goal(self, goal_id: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM goals WHERE id=?", (goal_id,))

    # --- segments --------------------------------------------------------

    def add_segment(self, seg: Segment) -> None:
        with self.con:
            self.con.execute(
                "INSERT INTO segments (task_id, day, started, ended, seconds, completed) VALUES (?,?,?,?,?,?)",
                (seg.task_id, seg.day.isoformat(), seg.started.isoformat(), seg.ended.isoformat(),
                 seg.seconds, int(seg.completed)),
            )

    def segments(self, start: date, end: date) -> list[Segment]:
        rows = self.con.execute(
            "SELECT * FROM segments WHERE day BETWEEN ? AND ? ORDER BY started",
            (start.isoformat(), end.isoformat()),
        )
        return [
            Segment(r["task_id"], _d(r["day"]), _dt(r["started"]), _dt(r["ended"]), r["seconds"], bool(r["completed"]))
            for r in rows
        ]

    # --- days ------------------------------------------------------------

    def day_row(self, day: date) -> dict | None:
        row = self.con.execute("SELECT * FROM days WHERE day=?", (day.isoformat(),)).fetchone()
        return dict(row) if row else None

    def days_where(self, sql_filter: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.con.execute(f"SELECT * FROM days WHERE {sql_filter} ORDER BY day", params)]

    def upsert_day(self, day: date, **values) -> None:
        cols = ["day", *values]
        with self.con:
            self.con.execute(
                f"INSERT INTO days ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                f" ON CONFLICT (day) DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in values)}",
                (day.isoformat(), *values.values()),
            )

    # --- timer -----------------------------------------------------------

    def load_timer(self) -> TimerState | None:
        row = self.con.execute("SELECT * FROM timer WHERE id=1").fetchone()
        if row is None:
            return None
        return TimerState(
            task_id=row["task_id"],
            phases=[Phase(p["kind"], p["minutes"]) for p in json.loads(row["phases_json"])],
            phase_index=row["phase_index"], phase_elapsed_s=row["phase_elapsed_s"],
            running=bool(row["running"]), resumed_at=_dt(row["resumed_at"]),
            heartbeat=_dt(row["heartbeat"]),
        )

    def save_timer(self, state: TimerState | None) -> None:
        with self.con:
            self.con.execute("DELETE FROM timer")
            if state is not None:
                self.con.execute(
                    "INSERT INTO timer (id, task_id, phases_json, phase_index, phase_elapsed_s, running, resumed_at, heartbeat)"
                    " VALUES (1,?,?,?,?,?,?,?)",
                    (state.task_id, json.dumps([{"kind": p.kind, "minutes": p.minutes} for p in state.phases]),
                     state.phase_index, state.phase_elapsed_s, int(state.running), _iso(state.resumed_at),
                     _iso(state.heartbeat)),
                )

