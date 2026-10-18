"""Pomodoro timer state machine. One timer at a time; state persists in the DB on every change."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Config
from .models import Phase, Segment, TimerState
from .pomodoro import split_phases
from .repo import Repo


class TimerError(ValueError):
    pass


@dataclass
class PhaseEnded:
    task_id: int
    phase: Phase
    next: Phase | None


@dataclass
class TaskCompleted:
    task_id: int


Event = PhaseEnded | TaskCompleted


class Timer:
    def __init__(self, repo: Repo, cfg: Config, clock: Callable[[], datetime]):
        self.repo = repo
        self.cfg = cfg
        self.clock = clock
        self.state: TimerState | None = repo.load_timer()

    # --- queries ---------------------------------------------------------

    def _elapsed(self, now: datetime) -> int:
        st = self.state
        extra = int((now - st.resumed_at).total_seconds()) if st.running and st.resumed_at else 0
        return st.phase_elapsed_s + extra

    def _phase_s(self) -> int:
        return self.state.phases[self.state.phase_index].minutes * 60

    def remaining_s(self) -> int:
        if self.state is None:
            return 0
        return max(0, self._phase_s() - self._elapsed(self.clock()))

    # --- internals -------------------------------------------------------

    def _alive(self) -> bool:
        """Drop a timer whose task no longer exists; True when a usable timer remains."""
        if self.state is None:
            return False
        try:
            self.repo.task(self.state.task_id)
        except KeyError:
            self.state = None
            self.repo.save_timer(None)
            return False
        return True

    def _save(self) -> None:
        self.repo.save_timer(self.state)
        if self.state is not None:
            self.repo.save_progress(self.state.task_id, self.state.phase_index, self.state.phase_elapsed_s)

    def _record(self, until: datetime, completed: bool) -> None:
        """Bank running time up to `until`; write a focus segment if this is a work phase."""
        st = self.state
        if not st.running or st.resumed_at is None:
            return
        seconds = max(0, int((until - st.resumed_at).total_seconds()))
        if st.phases[st.phase_index].kind == "work" and (seconds > 0 or completed):
            task = self.repo.task(st.task_id)
            self.repo.add_segment(Segment(st.task_id, task.day, st.resumed_at, until, seconds, completed))
        st.phase_elapsed_s += seconds
        st.resumed_at = until

    def _advance(self, at: datetime, natural: bool) -> list[Event]:
        st = self.state
        ended = st.phases[st.phase_index]
        nxt = st.phases[st.phase_index + 1] if st.phase_index + 1 < len(st.phases) else None
        events: list[Event] = [PhaseEnded(st.task_id, ended, nxt)]
        last_work = ended.kind == "work" and all(p.kind != "work" for p in st.phases[st.phase_index + 1:])
        if natural and last_work:
            self.repo.set_done(st.task_id, True, at)
            events.append(TaskCompleted(st.task_id))
        st.phase_index += 1
        st.phase_elapsed_s = 0
        if st.phase_index >= len(st.phases):
            self.repo.save_progress(st.task_id, 0, 0)
            self.state = None
        else:
            st.resumed_at = at if st.running else None
        return events

    # --- commands --------------------------------------------------------

    def start(self, task_id: int) -> list[Event]:
        task = self.repo.task(task_id)
        if task.kind == "check":
            raise TimerError("для галочки таймер не нужен")
        if task.done:
            raise TimerError("задача уже сделана")
        if self._alive():
            if self.state.task_id == task_id:
                if not self.state.running:
                    self.resume()
                return []
            self.stop()
        phases = split_phases(task.planned_min, self.cfg.work_min, self.cfg.break_min)
        index, elapsed = task.progress_phase, task.progress_elapsed_s
        if index >= len(phases) or elapsed >= phases[index].minutes * 60:
            index, elapsed = 0, 0
        self.state = TimerState(task_id, phases, index, elapsed, True, self.clock())
        self._save()
        return []

    def pause(self) -> None:
        if not self._alive() or not self.state.running:
            return
        self._record(self.clock(), completed=False)
        self.state.running = False
        self.state.resumed_at = None
        self._save()

    def resume(self) -> None:
        if not self._alive() or self.state.running:
            return
        self.state.running = True
        self.state.resumed_at = self.clock()
        self._save()

    def toggle(self) -> None:
        if self.state is None:
            return
        self.pause() if self.state.running else self.resume()

    def stop(self) -> None:
        if not self._alive():
            return
        self.pause()
        self.state = None
        self.repo.save_timer(None)

    def skip(self) -> list[Event]:
        if not self._alive():
            return []
        now = self.clock()
        self._record(now, completed=False)
        events = self._advance(now, natural=False)
        self._save() if self.state else self.repo.save_timer(None)
        return events

    def tick(self) -> list[Event]:
        events: list[Event] = []
        now = self.clock()
        if not self._alive():
            return events
        while self.state is not None and self.state.running:
            left = self._phase_s() - self._elapsed(now)
            if left > 0:
                break
            phase_end = self.state.resumed_at + timedelta(seconds=self._phase_s() - self.state.phase_elapsed_s)
            self._record(phase_end, completed=True)
            events += self._advance(phase_end, natural=True)
        if events:
            self._save() if self.state else self.repo.save_timer(None)
        return events

    def restore(self) -> None:
        """After a daemon restart: bank time up to now (capped at the phase end) and pause."""
        if not self._alive() or not self.state.running:
            return
        st = self.state
        phase_end = st.resumed_at + timedelta(seconds=self._phase_s() - st.phase_elapsed_s)
        self._record(min(self.clock(), phase_end), completed=False)
        st.running = False
        st.resumed_at = None
        self._save()
