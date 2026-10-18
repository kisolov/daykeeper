from datetime import datetime, timedelta

import pytest

from daykeeper.db import connect


class FakeClock:
    def __init__(self, start: datetime):
        self.current = start

    def now(self) -> datetime:
        return self.current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)

    def set(self, value: datetime) -> None:
        self.current = value


@pytest.fixture
def db(tmp_path):
    con = connect(tmp_path / "test.db")
    yield con
    con.close()


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 18, 9, 0, 0))
