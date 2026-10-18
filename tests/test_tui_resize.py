import pytest
from rich.text import Text

from daykeeper.config import Config
from daykeeper.service import Service
from daykeeper.tui.app import DaykeeperApp

from .tui_backend import FakeBackend

LONG = "очень длинное название задачи, которое точно не влезет в узкое окно"


@pytest.fixture
def svc(db, clock):
    s = Service(db, Config(), clock)
    for text in ("09:00-10:00 работа", "тренировка 2ч", LONG):
        s.call("task_quick_add", text=text)
    return s


def widths(text: str) -> list[int]:
    return [Text(line).cell_len for line in text.splitlines() if line.strip()]


@pytest.mark.parametrize("cols", [40, 60, 120])
async def test_today_rows_fill_window(svc, cols):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test(size=(cols, 30)) as pilot:
        await pilot.pause()
        screen = app.screen
        inner = cols - 4  # Screen padding: 2 each side
        rows = screen.list_text().splitlines()
        assert all(Text(r).cell_len == inner for r in rows), widths(screen.list_text())
        assert max(widths(screen.header_text())) == inner


async def test_long_title_is_truncated_not_wrapped(svc):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        row = app.screen.list_text().splitlines()[2]
        assert "…" in row and row.rstrip().endswith("✓")


async def test_today_redraws_on_resize(svc):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test(size=(50, 30)) as pilot:
        await pilot.pause()
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert all(Text(r).cell_len == 96 for r in app.screen.list_text().splitlines())


async def test_timer_bar_scales(svc):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("down", "enter")
        await pilot.pause()
        bar_line = next(line for line in app.screen.timer_text().splitlines() if "█" in line or "░" in line)
        assert bar_line.count("░") + bar_line.count("█") > 40


@pytest.mark.parametrize("cols,two_columns", [(60, False), (120, True)])
async def test_dashboard_layout_follows_width(svc, cols, two_columns):
    svc.call("tracker_add", name="сон", unit="ч")
    app = DaykeeperApp(FakeBackend(svc), start_screen="dash")
    async with app.run_test(size=(cols, 50)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert screen.two_columns is two_columns
        assert max(widths(screen.dash_text())) <= cols - 4
        assert "ФОКУС ЗА НЕДЕЛЮ" in screen.dash_text() and "ТРЕКЕРЫ" in screen.dash_text()


async def test_dashboard_redraws_on_resize(svc):
    app = DaykeeperApp(FakeBackend(svc), start_screen="dash")
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.resize_terminal(60, 50)
        await pilot.pause()
        assert app.screen.two_columns is False


async def test_key_hints_wrap_in_narrow_window(svc):
    app = DaykeeperApp(FakeBackend(svc))
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.press("down", "enter")
        await pilot.pause()
        footer = app.screen._shown["footer"]
        assert max(widths(footer)) <= 36
        for word in ("стоп", "завершить день", "выйти"):
            assert word in footer
