"""Plain data types shared by every layer."""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Literal

Kind = Literal["check", "timed", "duration"]
PhaseKind = Literal["work", "break"]
GoalKind = Literal["focus_tag", "tracker", "count_tag"]


@dataclass
class Task:
    id: int | None
    day: date
    title: str
    kind: Kind
    position: int = 0
    start: time | None = None
    end: time | None = None
    duration_min: int | None = None
    tag: str | None = None
    habit_id: int | None = None
    done: bool = False
    done_at: datetime | None = None
    progress_phase: int = 0
    progress_elapsed_s: int = 0

    @property
    def planned_min(self) -> int | None:
        if self.kind == "timed" and self.start and self.end:
            return (self.end.hour * 60 + self.end.minute) - (self.start.hour * 60 + self.start.minute)
        if self.kind == "duration":
            return self.duration_min
        return None


@dataclass
class Phase:
    kind: PhaseKind
    minutes: int


@dataclass
class Segment:
    task_id: int
    day: date
    started: datetime
    ended: datetime
    seconds: int
    completed: bool


@dataclass
class TimerState:
    task_id: int
    phases: list[Phase]
    phase_index: int
    phase_elapsed_s: int
    running: bool
    resumed_at: datetime | None
    heartbeat: datetime | None = None  # last tick while running; bounds crash/suspend credit


@dataclass
class Habit:
    id: int | None
    title: str
    weekdays: frozenset[int] = field(default_factory=lambda: frozenset(range(7)))
    tag: str | None = None
    active: bool = True


@dataclass
class Tracker:
    id: int | None
    name: str
    unit: str | None = None


@dataclass
class Goal:
    id: int | None
    title: str
    kind: GoalKind
    target: float
    created: date
    tag: str | None = None
    tracker_id: int | None = None
    period: Literal["week"] | None = None
    deadline: date | None = None
