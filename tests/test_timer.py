from datetime import date, datetime, time

import pytest

from daykeeper.config import Config
from daykeeper.models import Task
from daykeeper.repo import Repo
from daykeeper.timer import PhaseEnded, TaskCompleted, Timer, TimerError

D = date(2026, 10, 18)


@pytest.fixture
def env(db, clock):
    repo = Repo(db)
    return repo, Timer(repo, Config(), clock), clock


def add(repo, minutes=60, title="задача", kind="duration", day=D):
    if kind == "check":
        return repo.insert_task(Task(None, day, title, "check"), None)
    return repo.insert_task(Task(None, day, title, "duration", duration_min=minutes), None)


def run_for(timer, clock, seconds, step=5):
    """Let time pass the way the daemon sees it: a tick every few seconds."""
    events = []
    for _ in range(seconds // step):
        clock.advance(step)
        events += timer.tick()
    return events


def focus(repo):
    return sum(s.seconds for s in repo.segments(date.min, date.max))


def segs(repo):
    return [(s.seconds, s.completed) for s in repo.segments(date.min, date.max)]


def test_full_pomodoro(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    events = run_for(timer, clock, 47 * 60)
    assert events[0] == PhaseEnded(t.id, timer.state.phases[0], timer.state.phases[1])
    assert segs(repo) == [(2820, True)]
    assert timer.state.phase_index == 1 and timer.remaining_s() == 13 * 60


def test_tick_before_end_does_nothing(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    assert run_for(timer, clock, 100) == []
    assert timer.remaining_s() == 47 * 60 - 100


def test_partial_counts(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    clock.advance(40 * 60)
    timer.stop()
    assert segs(repo) == [(2400, False)]
    task = repo.task(t.id)
    assert (task.progress_phase, task.progress_elapsed_s) == (0, 2400)
    assert timer.state is None


def test_resume_continues(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    clock.advance(40 * 60)
    timer.stop()
    clock.advance(3600)
    timer.start(t.id)
    assert timer.state.phase_index == 0
    assert timer.remaining_s() == 7 * 60


def test_pause_resume(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    clock.advance(600)
    timer.pause()
    clock.advance(9999)
    assert timer.remaining_s() == 47 * 60 - 600
    timer.resume()
    clock.advance(60)
    timer.toggle()
    assert segs(repo) == [(600, False), (60, False)]
    assert not timer.state.running


def test_skip_work(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    clock.advance(600)
    events = timer.skip()
    assert segs(repo) == [(600, False)]
    assert timer.state.phases[timer.state.phase_index].kind == "break"
    assert isinstance(events[0], PhaseEnded)
    assert not repo.task(t.id).done


def test_skip_break_goes_to_work(env):
    repo, timer, clock = env
    t = add(repo, 120)
    timer.start(t.id)
    run_for(timer, clock, 47 * 60)
    timer.skip()
    assert timer.state.phase_index == 2 and timer.remaining_s() == 47 * 60


def test_autodone(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    events = run_for(timer, clock, 47 * 60)
    assert TaskCompleted(t.id) in events
    assert repo.task(t.id).done
    run_for(timer, clock, 13 * 60)
    assert timer.state is None


def test_single_timer(env):
    repo, timer, clock = env
    a, b = add(repo, 60, "a"), add(repo, 60, "b")
    timer.start(a.id)
    clock.advance(300)
    timer.start(b.id)
    assert segs(repo) == [(300, False)]
    assert timer.state.task_id == b.id and timer.state.running


def test_start_same_task_twice_is_noop(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    clock.advance(300)
    timer.start(t.id)
    assert segs(repo) == []
    assert timer.remaining_s() == 47 * 60 - 300


def test_check_task_rejected(env):
    repo, timer, _ = env
    t = add(repo, kind="check")
    with pytest.raises(TimerError):
        timer.start(t.id)


def test_done_task_rejected(env):
    repo, timer, clock = env
    t = add(repo, 60)
    repo.set_done(t.id, True, clock())
    with pytest.raises(TimerError):
        timer.start(t.id)


def test_restore_after_crash(env, clock):
    repo, timer, _ = env
    t = add(repo, 60)
    timer.start(t.id)
    run_for(timer, clock, 600)
    fresh = Timer(repo, Config(), clock)
    fresh.restore()
    assert not fresh.state.running
    assert 595 <= focus(repo) <= 600
    assert 37 * 60 <= fresh.remaining_s() <= 37 * 60 + 5


def test_power_loss_counts_only_until_last_heartbeat(env, clock):
    repo, timer, _ = env
    t = add(repo, 60)
    timer.start(t.id)
    run_for(timer, clock, 600)
    clock.advance(5 * 3600)  # laptop dead for hours
    fresh = Timer(repo, Config(), clock)
    fresh.restore()
    assert 595 <= focus(repo) <= 600
    assert not any(c for _, c in segs(repo))
    assert not repo.task(t.id).done


def test_midnight_day(env, clock):
    repo, timer, _ = env
    t = add(repo, 60)
    clock.set(datetime(2026, 10, 18, 23, 50))
    timer.start(t.id)
    clock.advance(30 * 60)
    timer.stop()
    assert repo.segments(date.min, date.max)[0].day == D


def test_suspend_does_not_count_as_focus(env):
    repo, timer, clock = env
    t = add(repo, 120)
    timer.start(t.id)
    run_for(timer, clock, 600)
    clock.advance(90 * 60)  # lid closed for lunch
    events = timer.tick()
    assert TaskCompleted(t.id) not in events
    assert focus(repo) == 600
    assert not timer.state.running
    assert timer.remaining_s() == 37 * 60
    assert not repo.task(t.id).done


def test_full_task_with_regular_ticks_completes(env):
    repo, timer, clock = env
    t = add(repo, 120)
    timer.start(t.id)
    events = run_for(timer, clock, 2 * 3600)
    assert TaskCompleted(t.id) in events
    assert segs(repo) == [(2820, True), (2820, True)]
    assert timer.state is None


def test_custom_durations(db, clock):
    repo = Repo(db)
    timer = Timer(repo, Config(work_min=25, break_min=5), clock)
    t = add(repo, 60)
    timer.start(t.id)
    assert timer.remaining_s() == 25 * 60 and len(timer.state.phases) == 4


def test_timed_task_uses_interval(env):
    repo, timer, _ = env
    t = repo.insert_task(Task(None, D, "w", "timed", start=time(9), end=time(10, 30)), None)
    timer.start(t.id)
    assert [p.minutes for p in timer.state.phases] == [47, 13, 30]


def test_restore_with_missing_task_clears_state(env, clock):
    repo, timer, _ = env
    t = add(repo, 60)
    timer.start(t.id)
    repo.con.execute("PRAGMA foreign_keys = OFF")
    repo.con.execute("DELETE FROM tasks WHERE id=?", (t.id,))
    repo.con.commit()
    fresh = Timer(repo, Config(), clock)
    fresh.restore()
    assert fresh.state is None and repo.load_timer() is None


def test_skip_marks_phase_end_unnatural(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    events = timer.skip()
    assert events[0].natural is False


def test_natural_phase_end_is_natural(env):
    repo, timer, clock = env
    t = add(repo, 60)
    timer.start(t.id)
    events = run_for(timer, clock, 47 * 60)
    assert events[0].natural is True
