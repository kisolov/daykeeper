"""The daemon: owns the DB, ticks the timer, sends reminders, serves RPC, runs the bot."""

import asyncio
import logging
import signal
from datetime import datetime

import httpx

from .config import Config
from .db import connect
from .notify import DesktopNotifier, Notifier
from .rpc import serve
from .scheduler import describe_events, due_reminders, reminder_text
from .service import Service, ServiceError
from .telegram import TelegramBot

log = logging.getLogger("daykeeper")


class Daemon:
    def __init__(self, cfg: Config, clock=datetime.now):
        self.cfg = cfg
        self.clock = clock
        self.service = Service(connect(cfg.db_path), cfg, clock)
        self.notifiers: list[Notifier] = [DesktopNotifier(self.handle_action)]
        self.bot: TelegramBot | None = None
        if cfg.tg_token and cfg.tg_chat_id:
            self.bot = TelegramBot(cfg.tg_token, cfg.tg_chat_id, self.service, httpx.AsyncClient())
            self.notifiers.append(self.bot)
        self.service.on_event = self._on_events
        self._last_check = clock()
        self._stop = asyncio.Event()

    def handle_action(self, key: str) -> None:
        """Action ids: `start:<task_id>` or `done:<task_id>`."""
        verb, _, raw = key.partition(":")
        method = {"start": "timer_start", "done": "task_done"}.get(verb)
        if not method or not raw.isdigit():
            return
        try:
            self.service.call(method, task_id=int(raw))
        except ServiceError as e:
            self._broadcast("daykeeper", e.message, {})

    def _title(self, task_id: int) -> str:
        try:
            return self.service.repo.task(task_id).title
        except KeyError:
            return "задача"

    def _broadcast(self, title: str, body: str, actions: dict[str, str]) -> None:
        loop = asyncio.get_running_loop()
        for n in self.notifiers:
            loop.create_task(self._safe_notify(n, title, body, actions))

    async def _safe_notify(self, n: Notifier, title: str, body: str, actions: dict[str, str]) -> None:
        try:
            await n.notify(title, body, actions)
        except Exception:
            log.exception("notifier failed")

    def _on_events(self, events) -> None:
        for title, body in describe_events(events, self._title):
            self._broadcast(title, body, {})

    def check_reminders(self) -> None:
        now = self.clock()
        tasks = self.service.repo.tasks(now.date())
        for task in due_reminders(tasks, self._last_check, now):
            title, body = reminder_text(task)
            self._broadcast(title, body, {f"start:{task.id}": "▶ Запустить", f"done:{task.id}": "✓ Сделано"})
        self._last_check = now

    async def run(self) -> None:
        self.service.timer.restore()
        server = await serve(self.service, self.cfg.socket_path)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._stop.set)
        extra = [asyncio.create_task(coro) for coro in self.background()]
        log.info("daykeeper daemon on %s", self.cfg.socket_path)
        try:
            while not self._stop.is_set():
                try:
                    self.service.tick()
                    self.check_reminders()
                    await server.publish()
                except Exception:
                    log.exception("tick failed")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1)
                except TimeoutError:
                    pass
        finally:
            for task in extra:
                task.cancel()
            self.service.timer.pause()
            await server.close()

    def background(self) -> list:
        """Extra long-running coroutines."""
        return [self.bot.run()] if self.bot else []


def run_daemon(cfg: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(Daemon(cfg).run())
