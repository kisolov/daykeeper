"""Desktop notifications via notify-send; action clicks come back through a callback."""

import asyncio
import shutil
from collections.abc import Callable
from typing import Protocol


class Notifier(Protocol):
    async def notify(self, title: str, body: str, actions: dict[str, str]) -> None: ...


class DesktopNotifier:
    def __init__(self, on_action: Callable[[str], None]):
        self.on_action = on_action
        self.binary = shutil.which("notify-send")

    async def notify(self, title: str, body: str, actions: dict[str, str]) -> None:
        if not self.binary:
            return
        args = [self.binary, "-a", "daykeeper", title, body]
        for key, label in actions.items():
            args[1:1] = ["-A", f"{key}={label}"]
        asyncio.get_running_loop().create_task(self._run(args, bool(actions)))

    async def _run(self, args: list[str], wait: bool) -> None:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        key = out.decode().strip()
        if wait and key:
            self.on_action(key)
