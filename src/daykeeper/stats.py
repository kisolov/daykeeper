"""Focus, streaks, goals, summaries and fact-based motivation. Read-only over Repo."""

from datetime import date, datetime, timedelta

from .models import Goal
from .repo import Repo


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def fmt_duration(seconds: int) -> str:
    minutes = int(seconds) // 60
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}ч{m}м"
    if h:
        return f"{h}ч"
    return f"{m}м"


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class Stats:
    def __init__(self, repo: Repo):
        self.repo = repo

    # --- focus -----------------------------------------------------------

    def focus_by_day(self, start: date, end: date) -> dict[date, int]:
        result = {d: 0 for d in _days(start, end)}
        for seg in self.repo.segments(start, end):
            result[seg.day] += seg.seconds
        return result

    def focus_total(self, start: date, end: date) -> int:
        return sum(self.focus_by_day(start, end).values())

    def pomodoros(self, day: date) -> int:
        return sum(1 for s in self.repo.segments(day, day) if s.completed)

    # --- habits ----------------------------------------------------------

    def _habit_marks(self, habit_id: int, until: date) -> dict[date, bool]:
        rows = self.repo.con.execute(
            "SELECT day, MAX(done) AS done FROM tasks WHERE habit_id=? AND day<=? GROUP BY day ORDER BY day",
            (habit_id, until.isoformat()),
        )
        return {date.fromisoformat(r["day"]): bool(r["done"]) for r in rows}

    def habit_grid(self, habit_id: int, end: date, days: int = 14) -> list[bool | None]:
        marks = self._habit_marks(habit_id, end)
        return [marks.get(d) for d in _days(end - timedelta(days=days - 1), end)]

    def habit_streak(self, habit_id: int, today: date) -> tuple[int, int]:
        marks = self._habit_marks(habit_id, today)
        ordered = sorted(marks.items())
        best = run = 0
        for _, done in ordered:
            run = run + 1 if done else 0
            best = max(best, run)
        current = 0
        for d, done in reversed(ordered):
            if d == today and not done:
                continue
            if not done:
                break
            current += 1
        return current, best

    # --- goals -----------------------------------------------------------

    def _window(self, goal: Goal, today: date) -> tuple[date, date]:
        if goal.period == "week":
            return _monday(today), today
        end = min(today, goal.deadline) if goal.deadline else today
        return goal.created, end

    def goal_progress(self, goal: Goal, today: date) -> dict:
        start, end = self._window(goal, today)
        initial = None
        if goal.kind == "focus_tag":
            row = self.repo.con.execute(
                "SELECT COALESCE(SUM(s.seconds), 0) FROM segments s JOIN tasks t ON t.id = s.task_id"
                " WHERE t.tag=? AND s.day BETWEEN ? AND ?",
                (goal.tag, start.isoformat(), end.isoformat()),
            ).fetchone()
            value = row[0] / 3600
        elif goal.kind == "count_tag":
            row = self.repo.con.execute(
                "SELECT COUNT(*) FROM tasks WHERE tag=? AND done=1 AND day BETWEEN ? AND ?",
                (goal.tag, start.isoformat(), end.isoformat()),
            ).fetchone()
            value = row[0]
        else:
            entries = self.repo.tracker_entries(goal.tracker_id, goal.created, today)
            value = entries[-1][1] if entries else None
            initial = entries[0][1] if entries else None

        expected = None
        if goal.period == "week":
            expected = goal.target * (today.weekday() + 1) / 7
        elif goal.deadline:
            span = (goal.deadline - goal.created).days or 1
            frac = min(1.0, max(0.0, (today - goal.created).days / span))
            if goal.kind == "tracker":
                expected = None if initial is None else initial + (goal.target - initial) * frac
            else:
                expected = goal.target * frac

        delta = None if expected is None or value is None else value - expected
        if delta is None:
            behind = False
        elif goal.kind == "tracker" and initial is not None and goal.target < initial:
            behind = delta > 0
        else:
            behind = delta < 0
        return {
            "id": goal.id, "title": goal.title, "kind": goal.kind, "target": goal.target,
            "value": value, "start": initial, "expected": expected, "delta": delta, "behind": behind,
            "period": goal.period, "deadline": goal.deadline.isoformat() if goal.deadline else None,
        }

    # --- motivation ------------------------------------------------------

    def motivation(self, today: date) -> str | None:
        monday = _monday(today)
        this_week = self.focus_total(monday, today)
        previous = [self.focus_total(monday - timedelta(weeks=i), monday - timedelta(weeks=i) + timedelta(days=6))
                    for i in (1, 2, 3)]
        if this_week > 0 and any(previous) and this_week > max(previous):
            return "лучшая неделя по фокусу за месяц"

        for habit in self.repo.habits(active_only=True):
            current, best = self.habit_streak(habit.id, today)
            if current >= 3:
                days = f"{current} {plural(current, 'день', 'дня', 'дней')} подряд"
                if current >= best:
                    return f"{habit.title} — {days}, новый рекорд"
                if best - current <= 3:
                    return f"{habit.title} — {days}, рекорд {best}"

        today_s = self.focus_total(today, today)
        yesterday_s = self.focus_total(today - timedelta(days=1), today - timedelta(days=1))
        if today_s > yesterday_s and yesterday_s > 0 and today_s - yesterday_s >= 60:
            return f"сегодня на {fmt_duration(today_s - yesterday_s)} больше фокуса, чем вчера"
        return None

    # --- summaries -------------------------------------------------------

    def day_summary(self, day: date) -> dict:
        tasks = self.repo.tasks(day)
        habits = []
        for t in tasks:
            if t.habit_id is not None:
                habits.append({"title": t.title, "done": t.done, "streak": self.habit_streak(t.habit_id, day)[0]})
        return {
            "day": day.isoformat(),
            "done": [t.title for t in tasks if t.done],
            "not_done": [t.title for t in tasks if not t.done],
            "focus_s": self.focus_total(day, day),
            "pomodoros": self.pomodoros(day),
            "habits": habits,
            "goals": [self.goal_progress(g, day) for g in self.repo.goals()],
            "motivation": self.motivation(day),
        }

    def dashboard(self, now: datetime) -> dict:
        today = now.date()
        tasks = self.repo.tasks(today)
        upcoming = [t for t in tasks if t.kind == "timed" and not t.done and t.start >= now.time().replace(second=0, microsecond=0)]
        monday = _monday(today)
        week = self.focus_by_day(monday, monday + timedelta(days=6))
        prev_monday = monday - timedelta(weeks=1)
        return {
            "today": {
                "day": today.isoformat(),
                "done": sum(t.done for t in tasks), "total": len(tasks),
                "focus_s": self.focus_total(today, today), "pomodoros": self.pomodoros(today),
                "next_timed": {"title": upcoming[0].title, "start": f"{upcoming[0].start:%H:%M}"} if upcoming else None,
            },
            "week": {
                "start": monday.isoformat(),
                "days": [{"day": d.isoformat(), "focus_s": s} for d, s in week.items()],
                "total_s": sum(week.values()),
                "prev_total_s": self.focus_total(prev_monday, prev_monday + timedelta(days=6)),
            },
            "goals": [self.goal_progress(g, today) for g in self.repo.goals()],
            "habits": [
                {"id": h.id, "title": h.title, "grid": self.habit_grid(h.id, today),
                 "streak": self.habit_streak(h.id, today)[0], "best": self.habit_streak(h.id, today)[1]}
                for h in self.repo.habits(active_only=True)
            ],
            "trackers": [self._tracker_view(tr, today) for tr in self.repo.trackers()],
            "motivation": self.motivation(today),
        }

    def _tracker_view(self, tracker, today: date) -> dict:
        start = today - timedelta(days=6)
        values = dict(self.repo.tracker_entries(tracker.id, start, today))
        all_entries = self.repo.tracker_entries(tracker.id, None, today)
        return {
            "id": tracker.id, "name": tracker.name, "unit": tracker.unit,
            "last": all_entries[-1][1] if all_entries else None,
            "series": [values.get(d) for d in _days(start, today)],
        }
