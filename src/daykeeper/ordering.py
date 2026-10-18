"""The single ordering rule: a later-timed task never sits above an earlier-timed one.

All functions take tasks in their current order and return a new list;
the caller rewrites positions as 0..n-1.
"""

from collections.abc import Sequence

from .models import Task


class OrderError(ValueError):
    pass


def _first_violation(tasks: Sequence[Task]) -> tuple[Task, Task] | None:
    prev: Task | None = None
    for task in tasks:
        if task.kind == "timed" and task.start is not None:
            if prev is not None and task.start < prev.start:
                return prev, task
            prev = task
    return None


def is_valid(tasks: Sequence[Task]) -> bool:
    return _first_violation(tasks) is None


def insert_index(tasks: Sequence[Task], new: Task) -> int:
    if new.kind != "timed" or new.start is None:
        return len(tasks)
    for i, task in enumerate(tasks):
        if task.kind == "timed" and task.start is not None and task.start > new.start:
            return i
    return len(tasks)


def _index_of(tasks: Sequence[Task], task_id: int) -> int:
    for i, task in enumerate(tasks):
        if task.id == task_id:
            return i
    raise KeyError(task_id)


def _placed(tasks: Sequence[Task], task_id: int, index: int) -> list[Task]:
    i = _index_of(tasks, task_id)
    rest = list(tasks[:i]) + list(tasks[i + 1:])
    index = max(0, min(index, len(rest)))
    return rest[:index] + [tasks[i]] + rest[index:]


def move(tasks: Sequence[Task], task_id: int, index: int) -> list[Task]:
    result = _placed(tasks, task_id, index)
    bad = _first_violation(result)
    if bad:
        upper, lower = bad
        raise OrderError(
            f"задача {upper.start:%H:%M} не может стоять выше {lower.start:%H:%M}"
        )
    return result


def settle(tasks: Sequence[Task], task_id: int) -> list[Task]:
    if is_valid(tasks):
        return list(tasks)
    current = _index_of(tasks, task_id)
    for distance in range(1, len(tasks)):
        for index in (current - distance, current + distance):
            if 0 <= index < len(tasks):
                candidate = _placed(tasks, task_id, index)
                if is_valid(candidate):
                    return candidate
    raise OrderError("не удалось расставить задачи по времени")
