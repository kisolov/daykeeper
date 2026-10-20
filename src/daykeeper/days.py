"""Day lifecycle: habits spawn into the list, past days auto-close with a summary snapshot."""

import json
from collections.abc import Callable
from datetime import date, datetime

from .models import Habit, Task
from .repo import Repo


class Days:
    def __init__(self, repo: Repo, summarize: Callable[[date], dict], clock: Callable[[], datetime]):
        self.repo = repo
        self.summarize = summarize
        self.clock = clock

    def ensure(self, day: date) -> None:
        """Spawn habits into `day` (today or later only) and auto-close days before the real today."""
        today = self.clock().date()
        row = self.repo.day_row(day)
        if day >= today and (not row or not row["spawned"]):
            for habit in self.repo.habits(active_only=True):
                self._spawn(habit, day)
            self.repo.upsert_day(day, spawned=1)
        self._autoclose_before(min(day, today))

    def spawn_habit(self, habit: Habit) -> None:
        """A new habit joins today and the future days already spawned (later ones get it from `ensure`)."""
        today = self.clock().date()
        for row in self.repo.days_where("spawned=1 AND day >= ?", (today.isoformat(),)):
            self._spawn(habit, date.fromisoformat(row["day"]))

    def _spawn(self, habit: Habit, day: date) -> None:
        if day.weekday() in habit.weekdays:
            self.repo.insert_task(
                Task(None, day, habit.title, "check", tag=habit.tag, habit_id=habit.id), len(self.repo.tasks(day))
            )

    def _autoclose_before(self, day: date) -> None:
        rows = self.repo.con.execute(
            "SELECT DISTINCT t.day FROM tasks t LEFT JOIN days d ON d.day = t.day"
            " WHERE t.day < ? AND COALESCE(d.closed, 0) = 0 ORDER BY t.day",
            (day.isoformat(),),
        ).fetchall()
        for (past,) in rows:
            d = date.fromisoformat(past)
            self.repo.upsert_day(d, closed=1, summary_seen=0, summary_json=json.dumps(self.summarize(d), ensure_ascii=False))

    def close(self, day: date) -> dict:
        summary = self.summarize(day)
        self.repo.upsert_day(day, closed=1, summary_seen=1, summary_json=json.dumps(summary, ensure_ascii=False))
        return summary

    def pending_summary(self) -> tuple[date, dict] | None:
        rows = self.repo.days_where("closed=1 AND summary_seen=0 AND summary_json IS NOT NULL")
        if not rows:
            return None
        last = rows[-1]
        return date.fromisoformat(last["day"]), json.loads(last["summary_json"])

    def mark_seen(self, day: date) -> None:
        with self.repo.con:
            self.repo.con.execute("UPDATE days SET summary_seen=1 WHERE day <= ?", (day.isoformat(),))
