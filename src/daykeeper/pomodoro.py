"""Split a task's wall-clock duration into work/break phases."""

from .models import Phase


def split_phases(total_min: int, work_min: int = 47, break_min: int = 13) -> list[Phase]:
    if total_min <= 0:
        raise ValueError("длительность должна быть больше нуля")
    phases: list[Phase] = []
    left = total_min
    while left > 0:
        work = min(left, work_min)
        phases.append(Phase("work", work))
        left -= work
        rest = min(left, break_min)
        if rest > 0:
            phases.append(Phase("break", rest))
            left -= rest
    return phases


def work_minutes(phases: list[Phase]) -> int:
    return sum(p.minutes for p in phases if p.kind == "work")


def pomodoro_count(total_min: int, work_min: int = 47, break_min: int = 13) -> int:
    return sum(1 for p in split_phases(total_min, work_min, break_min) if p.kind == "work")
