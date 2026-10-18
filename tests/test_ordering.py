from datetime import date, time

import pytest

from daykeeper.models import Task
from daykeeper.ordering import OrderError, insert_index, is_valid, move, settle


def t(id, kind, start=None, end=None, dur=None):
    def hm(s):
        return time.fromisoformat(s) if s else None
    return Task(id, date(2026, 10, 18), f"t{id}", kind, start=hm(start), end=hm(end), duration_min=dur)


def day():
    return [t(1, "timed", "09:00", "10:00"), t(2, "check"), t(3, "duration", dur=120),
            t(4, "check"), t(5, "timed", "19:00", "20:00")]


def ids(ts):
    return [x.id for x in ts]


def test_valid_day():
    assert is_valid(day())


def test_free_task_moves_anywhere():
    assert ids(move(day(), 2, 4)) == [1, 3, 4, 5, 2]


def test_free_task_above_first_timed():
    assert ids(move(day(), 4, 0)) == [4, 1, 2, 3, 5]


def test_timed_moves_among_free():
    assert ids(move(day(), 5, 2)) == [1, 2, 5, 3, 4]


def test_timed_cannot_pass_earlier():
    with pytest.raises(OrderError, match="19:00 не может стоять выше 09:00"):
        move(day(), 5, 0)


def test_move_does_not_mutate_input():
    ts = day()
    move(ts, 2, 4)
    assert ids(ts) == [1, 2, 3, 4, 5]


def test_insert_timed_before_next_later_timed():
    assert insert_index(day(), t(9, "timed", "15:00", "16:00")) == 4


def test_insert_timed_earliest():
    assert insert_index(day(), t(9, "timed", "07:00", "08:00")) == 0


def test_insert_timed_latest():
    assert insert_index(day(), t(9, "timed", "21:00", "22:00")) == 5


def test_insert_free():
    assert insert_index(day(), t(9, "check")) == 5


def test_settle_after_time_change():
    ts = day()
    ts[4].start = time(8)
    assert ids(settle(ts, 5)) == [5, 1, 2, 3, 4]


def test_settle_keeps_valid_position():
    ts = day()
    ts[4].start = time(18)
    assert ids(settle(ts, 5)) == [1, 2, 3, 4, 5]
