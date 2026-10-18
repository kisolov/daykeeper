"""What to notify about: due timed tasks and timer events. Pure functions."""

from collections.abc import Callable
from datetime import datetime

from .models import Task
from .timer import Event, PhaseEnded, TaskCompleted


def due_reminders(tasks: list[Task], since: datetime, now: datetime) -> list[Task]:
    due = []
    for t in tasks:
        if t.kind != "timed" or t.done or t.start is None:
            continue
        at = datetime.combine(t.day, t.start)
        if since < at <= now:
            due.append(t)
    return due


def reminder_text(task: Task) -> tuple[str, str]:
    return f"пора: {task.title}", f"{task.start:%H:%M}–{task.end:%H:%M}"


def describe_events(events: list[Event], title_of: Callable[[int], str]) -> list[tuple[str, str]]:
    completed = {e.task_id for e in events if isinstance(e, TaskCompleted)}
    out: list[tuple[str, str]] = []
    for e in events:
        if not isinstance(e, PhaseEnded):
            continue
        title = title_of(e.task_id)
        if e.phase.kind == "work" and e.task_id in completed:
            out.append((f"готово: {title}", f"отдых {e.next.minutes}м" if e.next else ""))
        elif e.phase.kind == "work":
            out.append((f"перерыв {e.next.minutes}м" if e.next else f"готово: {title}", title if e.next else ""))
        elif e.next is not None:
            out.append((f"снова работа: {title}", f"{e.next.minutes}м"))
        else:
            out.append(("отдых закончился", title))
    return out
