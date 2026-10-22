from datetime import datetime

import pytest

from daykeeper.config import Config
from daykeeper.service import Service
from daykeeper.tui.app import DaykeeperApp
from daykeeper.tui.summary import SummaryScreen
from daykeeper.tui.today import TodayScreen
from daykeeper.tui.widgets import POMODORO, TIMER

from .tui_backend import DownBackend, FakeBackend


@pytest.fixture
def svc(db, clock):
    return Service(db, Config(), clock)


@pytest.fixture
def day_svc(svc):
    for text in ("09:00-10:00 работа", "почистить зубы", "тренировка 2ч", "прочитать 20 страниц", "19:00-20:00 VPN-бот"):
        svc.call("task_quick_add", text=text)
    return svc


def today(app) -> TodayScreen:
    assert isinstance(app.screen, TodayScreen)
    return app.screen


def lines(app):
    return today(app).list_text().splitlines()


async def test_rows_in_order_without_groups(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.pause()
        text = today(app).list_text()
        assert "ГАЛОЧКИ" not in text and "ПО ВРЕМЕНИ" not in text
        rows = lines(app)
        assert [r.split("]", 1)[1].strip().split("  ")[0] for r in rows] == [
            "09–10 работа", "почистить зубы", "тренировка", "прочитать 20 страниц", "19–20 VPN-бот"]
        assert rows[1].rstrip().endswith("✓")
        assert rows[2].rstrip().endswith(f"{TIMER} 2ч · 2{POMODORO}")
        assert rows[0].rstrip().endswith(f"1{POMODORO}")


async def test_header(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.pause()
        header = today(app).header_text()
        assert "СЕГОДНЯ · вс 18 окт" in header and "0/5" in header


async def test_space_marks_done(day_svc):
    backend = FakeBackend(day_svc)
    app = DaykeeperApp(backend)
    async with app.run_test() as pilot:
        await pilot.press("down", "space")
        await pilot.pause()
        assert ("task_done", {"task_id": 2, "done": True}) in backend.calls
        assert lines(app)[1].lstrip(" ›").startswith("[x]")
        await pilot.press("space")
        await pilot.pause()
        assert lines(app)[1].lstrip(" ›").startswith("[ ]")


async def test_enter_starts_timer(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        panel = today(app).timer_text()
        assert "тренировка" in panel and "помидор 1 из 2" in panel and "47:00" in panel
        assert "[▶]" in lines(app)[2]


async def test_enter_on_check_warns(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.press("down", "enter")
        await pilot.pause()
        assert today(app).timer_text() == ""
        assert any("галочки" in n.message for n in app._notifications)


async def test_pause_and_stop(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.press("down", "down", "enter", "p")
        await pilot.pause()
        assert "пауза" in today(app).timer_text()
        await pilot.press("x")
        await pilot.pause()
        assert today(app).timer_text() == ""


async def test_move_violation_toast(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.press("end")
        for _ in range(4):
            await pilot.press("K")
        await pilot.pause()
        assert lines(app)[0].split("]", 1)[1].strip().startswith("09–10 работа")
        assert any("не может стоять выше" in n.message for n in app._notifications)


async def test_move_free_task(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.press("down", "J")
        await pilot.pause()
        assert "почистить зубы" in lines(app)[2]
        assert lines(app)[2].startswith(" ›") or lines(app)[2].startswith("›")


async def test_quick_add(svc):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test() as pilot:
        await pilot.press("a")
        await pilot.press(*"тренировка 2ч")
        await pilot.press("enter")
        await pilot.pause()
        assert lines(app)[0].rstrip().endswith(f"{TIMER} 2ч · 2{POMODORO}")


async def test_quick_add_bad_input(svc):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test() as pilot:
        await pilot.press("a", *"10:00-09:00 x", "enter")
        await pilot.pause()
        assert today(app).list_text().strip() == "пусто — a добавить или попроси Claude"
        assert any("конец раньше начала" in n.message for n in app._notifications)


async def test_day_navigation(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.press("]")
        await pilot.pause()
        assert "ЗАВТРА · пн 19 окт" in today(app).header_text()
        await pilot.press("[", "[")
        await pilot.pause()
        assert "ВЧЕРА · сб 17 окт" in today(app).header_text()


async def test_pending_yesterday(svc, clock):
    svc.call("task_quick_add", text="зубы")
    clock.set(datetime(2026, 10, 19, 9))
    backend = FakeBackend(svc)
    app = DaykeeperApp(backend)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SummaryScreen)
        assert "зубы" in app.screen.body_text()
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, TodayScreen)
        assert ("summary_seen", {"day": "2026-10-18"}) in backend.calls


async def test_daemon_down():
    app = DaykeeperApp(DownBackend())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "демон не запущен" in today(app).header_text()


async def test_end_day_when_daemon_down_does_not_crash():
    app = DaykeeperApp(DownBackend())
    async with app.run_test() as pilot:
        await pilot.press("e", "a", "space", "enter", "J", "]")
        await pilot.pause()
        assert "демон не запущен" in today(app).header_text()


async def test_reconnects_when_daemon_comes_up(svc):
    from .tui_backend import FlakyBackend
    import asyncio
    svc.call("task_quick_add", text="зубы")
    backend = FlakyBackend(svc)
    app = DaykeeperApp(backend)
    app.RETRY_S = 0.05
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "демон не запущен" in today(app).header_text()
        backend.up = True
        await asyncio.sleep(0.3)
        await pilot.pause()
        assert "СЕГОДНЯ" in today(app).header_text()
        assert "зубы" in today(app).list_text()


async def test_switches_to_new_day_after_midnight(svc, clock):
    import asyncio
    svc.call("task_quick_add", text="зубы")
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test() as pilot:
        await pilot.pause()
        clock.set(datetime(2026, 10, 19, 0, 0, 5))
        svc.tick()
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert "СЕГОДНЯ · пн 19 окт" in today(app).header_text()


async def test_refreshes_after_external_reorder(day_svc):
    import asyncio
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.pause()
        day_svc.call("task_move", task_id=4, index=1)  # e.g. Claude over MCP
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert "прочитать 20 страниц" in lines(app)[1]


async def test_pending_summary_closes_on_russian_layout(svc, clock):
    """With the ru layout active the q key arrives as «й»; the summary must still close."""
    svc.call("task_quick_add", text="зубы")
    clock.set(datetime(2026, 10, 19, 9))
    backend = FakeBackend(svc)
    app = DaykeeperApp(backend)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SummaryScreen)
        await pilot.press("й")
        await pilot.pause()
        assert isinstance(app.screen, TodayScreen)
        assert ("summary_seen", {"day": "2026-10-18"}) in backend.calls


async def test_today_keys_work_on_russian_layout(day_svc):
    app = DaykeeperApp(FakeBackend(day_svc))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("о", "о")  # j j
        await pilot.pause()
        assert today(app).cursor == 2
        await pilot.press("ъ")  # ]
        await pilot.pause()
        assert "ЗАВТРА" in today(app).header_text()
        await pilot.press("в")  # d
        await pilot.pause()
        assert type(app.screen).__name__ == "DashboardScreen"
        await pilot.press("й")  # q: back to today
        await pilot.pause()
        assert isinstance(app.screen, TodayScreen)
