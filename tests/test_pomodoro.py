import pytest

from daykeeper.pomodoro import pomodoro_count, split_phases, work_minutes

W, B = "work", "break"


@pytest.mark.parametrize("total,expected", [
    (60, [(W, 47), (B, 13)]),
    (120, [(W, 47), (B, 13), (W, 47), (B, 13)]),
    (90, [(W, 47), (B, 13), (W, 30)]),
    (30, [(W, 30)]),
    (50, [(W, 47), (B, 3)]),
])
def test_split(total, expected):
    assert [(p.kind, p.minutes) for p in split_phases(total)] == expected


def test_split_custom():
    assert [(p.kind, p.minutes) for p in split_phases(60, 25, 5)] == [(W, 25), (B, 5), (W, 25), (B, 5)]


@pytest.mark.parametrize("bad", [0, -5])
def test_split_rejects_non_positive(bad):
    with pytest.raises(ValueError):
        split_phases(bad)


def test_count():
    assert pomodoro_count(120) == 2
    assert pomodoro_count(60) == 1
    assert pomodoro_count(90) == 2


def test_work_minutes():
    assert work_minutes(split_phases(90)) == 77
