from datetime import date, datetime, timedelta

import pytest

from daykeeper.config import Config
from daykeeper.models import Segment
from daykeeper.service import Service
from daykeeper.tui.app import DaykeeperApp
from daykeeper.tui.dashboard import DashboardScreen
from daykeeper.tui.summary import SummaryScreen

from .tui_backend import FakeBackend


@pytest.fixture
def svc(db, clock):
    return Service(db, Config(), clock)


async def test_end_day_shows_summary(svc):
    svc.call("task_quick_add", text="зубы")
    t = svc.call("task_quick_add", text="чтение")
    svc.call("task_done", task_id=t["id"])
    backend = FakeBackend(svc)
    app = DaykeeperApp(backend)
    async with app.run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, SummaryScreen)
        body = app.screen.body_text()
        assert "сделано\n [x] чтение" in body and "не сделано\n [ ] зубы" in body
        assert ("day_close", {"day": "2026-10-18"}) in backend.calls


async def test_dashboard_empty(svc):
    app = DaykeeperApp(FakeBackend(svc), start_screen="dash")
    async with app.run_test(size=(90, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        text = app.screen.dash_text()
        assert "ДАШБОРД · неделя 42" in text and "ФОКУС ЗА НЕДЕЛЮ" in text
        assert "»" not in text


async def test_dashboard_with_data(svc, clock):
    h = svc.call("habit_add", title="зарядка")
    for i in range(1, 4):
        day = (date(2026, 10, 18) - timedelta(days=i)).isoformat()
        tid = svc.call("day_get", day=day)["tasks"][0]["id"]
        svc.call("task_done", task_id=tid)
    t = svc.call("task_add", title="бот", kind="duration", duration_min=60, tag="bot")
    svc.repo.add_segment(Segment(t["id"], date(2026, 10, 18), datetime(2026, 10, 18, 8), datetime(2026, 10, 18, 9), 3600, True))
    svc.call("goal_add", title="бот 20ч", kind="focus_tag", target=20, tag="bot", period="week")
    svc.call("tracker_add", name="сон", unit="ч")
    svc.call("tracker_log", tracker="сон", value=7.5)
    app = DaykeeperApp(FakeBackend(svc), start_screen="dash")
    async with app.run_test(size=(90, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SummaryScreen)  # auto-closed yesterday shows first, once
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        text = app.screen.dash_text()
        habit_line = next(line for line in text.splitlines() if "зарядка" in line)
        assert habit_line.count("■") + habit_line.count("□") + habit_line.count("·") >= 14
        assert "🔥3" in habit_line
        assert "от темпа" in text and "бот 20ч" in text
        assert "сон" in text and "7.5" in text
        assert "» зарядка — 3 дня подряд, новый рекорд" in text
        assert h["title"] == "зарядка"


async def test_week_navigation(svc):
    app = DaykeeperApp(FakeBackend(svc), start_screen="dash")
    async with app.run_test(size=(90, 40)) as pilot:
        await pilot.press("left")
        await pilot.pause()
        assert "неделя 41" in app.screen.dash_text()
        await pilot.press("t")
        await pilot.pause()
        assert "неделя 42" in app.screen.dash_text()


async def test_dashboard_back_to_today(svc):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test() as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, DashboardScreen)
