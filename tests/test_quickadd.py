from datetime import time

import pytest

from daykeeper.quickadd import parse_quick_add


def test_check():
    assert parse_quick_add("почистить зубы") == {
        "title": "почистить зубы", "kind": "check", "start": None, "end": None, "duration_min": None,
    }


def test_timed():
    r = parse_quick_add("09:00-10:00 работа")
    assert (r["kind"], r["start"], r["end"], r["title"]) == ("timed", time(9), time(10), "работа")


def test_timed_short_hour_and_dash():
    r = parse_quick_add("9:30–11:00 созвон с командой")
    assert (r["start"], r["end"], r["title"]) == (time(9, 30), time(11), "созвон с командой")


def test_hours():
    assert parse_quick_add("тренировка 2ч")["duration_min"] == 120


def test_minutes():
    r = parse_quick_add("учёба 90м")
    assert (r["kind"], r["duration_min"], r["title"]) == ("duration", 90, "учёба")


def test_mixed():
    assert parse_quick_add("код 1ч30м")["duration_min"] == 90


def test_strips_whitespace():
    assert parse_quick_add("  зарядка  ")["title"] == "зарядка"


@pytest.mark.parametrize("bad", ["", "   ", "25:00-26:00 x", "10:00-09:00 x", "x 0м", "09:00-10:00", "2ч"])
def test_bad(bad):
    with pytest.raises(ValueError):
        parse_quick_add(bad)
