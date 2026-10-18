"""Textual app: screens plus one live subscription to the daemon."""

import asyncio

from textual.app import App

from ..rpc import DaemonDown
from .today import TodayScreen


class DaykeeperApp(App):
    CSS_PATH = "lumon.tcss"
    RETRY_S = 2.0
    TITLE = "daykeeper"

    def __init__(self, backend, start_screen: str = "today"):
        super().__init__()
        self.backend = backend
        self.start_screen = start_screen

    def on_mount(self) -> None:
        self.push_screen(TodayScreen(self.backend))
        if self.start_screen == "dash":
            from .dashboard import DashboardScreen
            self.push_screen(DashboardScreen(self.backend))
        self.run_worker(self._listen(), exclusive=True, exit_on_error=False)

    async def _listen(self) -> None:
        """Follow the daemon forever: reconnect after it restarts, show «down» meanwhile."""
        while True:
            try:
                async for state in self.backend.subscribe():
                    for screen in self.screen_stack:
                        if hasattr(screen, "live"):
                            screen.live(state)
            except (DaemonDown, ConnectionError, OSError):
                pass
            for screen in self.screen_stack:
                if hasattr(screen, "live_down"):
                    screen.live_down()
            await asyncio.sleep(self.RETRY_S)


def run_tui(backend, start_screen: str = "today") -> None:
    DaykeeperApp(backend, start_screen).run()
