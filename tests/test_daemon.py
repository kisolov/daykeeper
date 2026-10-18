from datetime import datetime, timedelta

import pytest

from daykeeper.config import Config
from daykeeper.daemon import Daemon
from daykeeper.models import Phase
from daykeeper.timer import PhaseEnded


class Rec:
    def __init__(self):
        self.played = []
        self.sent = []

    def play(self, kind):
        self.played.append(kind)

    async def notify(self, title, body, actions):
        self.sent.append(title)


@pytest.fixture
def daemon(tmp_path, clock):
    d = Daemon(Config(db_path=tmp_path / "d.db", socket_path=tmp_path / "s.sock"), clock=clock)
    rec = Rec()
    d.sound = rec
    d.notifiers = [rec]
    return d, rec, clock


async def test_reminder_plays_one_sound(daemon):
    d, rec, clock = daemon
    start = (clock() + timedelta(minutes=1)).strftime("%H:%M")
    end = (clock() + timedelta(minutes=61)).strftime("%H:%M")
    d.service.call("task_add", title="a", kind="timed", start=start, end=end)
    d.service.call("task_add", title="b", kind="timed", start=start, end=end)
    clock.advance(61)
    d.check_reminders()
    assert rec.played == ["reminder"]


async def test_no_reminder_no_sound(daemon):
    d, rec, clock = daemon
    clock.advance(61)
    d.check_reminders()
    assert rec.played == []


async def test_phase_end_plays_sound(daemon):
    d, rec, _ = daemon
    d._on_events([PhaseEnded(1, Phase("work", 47), Phase("break", 13))])
    assert rec.played == ["break"]


async def test_manual_skip_is_silent(daemon):
    d, rec, _ = daemon
    d._on_events([PhaseEnded(1, Phase("work", 47), Phase("break", 13), natural=False)])
    assert rec.played == []


def test_clock_default_is_wall_time(tmp_path):
    d = Daemon(Config(db_path=tmp_path / "d.db", socket_path=tmp_path / "s.sock"))
    assert abs((d.clock() - datetime.now()).total_seconds()) < 5
