from datetime import date, time

from daykeeper.db import connect
from daykeeper.models import Task


def test_connect_creates_schema(tmp_path):
    con = connect(tmp_path / "a" / "x.db")
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"tasks", "habits", "trackers", "tracker_entries", "goals", "segments", "days", "timer"} <= names
    assert con.execute("pragma user_version").fetchone()[0] == 1


def test_connect_is_idempotent(tmp_path):
    connect(tmp_path / "x.db").close()
    con = connect(tmp_path / "x.db")
    assert con.execute("pragma user_version").fetchone()[0] == 1


def test_planned_min():
    d = date(2026, 10, 18)
    assert Task(1, d, "w", "timed", 0, start=time(9), end=time(10, 30)).planned_min == 90
    assert Task(1, d, "w", "duration", 0, duration_min=120).planned_min == 120
    assert Task(1, d, "w", "check", 0).planned_min is None
