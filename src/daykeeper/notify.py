"""Desktop notifications via notify-send; action clicks come back through a callback."""

import asyncio
import shutil
from collections.abc import Callable
from typing import Protocol

from .config import Config


_THEME = "/usr/share/sounds/freedesktop/stereo"
SOUNDS = {
    "reminder": f"{_THEME}/message.oga",
    "break": f"{_THEME}/complete.oga",
    "work": f"{_THEME}/dialog-information.oga",
    "done": f"{_THEME}/complete.oga",
}


def sound_command(kind: str, cfg: Config, which: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    if not cfg.sound or kind not in SOUNDS:
        return None
    if player := which("pw-play"):
        return [player, "--volume", f"{cfg.sound_volume:g}", SOUNDS[kind]]
    if player := which("paplay"):
        return [player, "--volume", str(int(cfg.sound_volume * 65536)), SOUNDS[kind]]
    return None


class SoundPlayer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._tasks: set[asyncio.Task] = set()

    def play(self, kind: str | None) -> None:
        cmd = sound_command(kind, self.cfg) if kind else None
        if cmd:
            task = asyncio.get_running_loop().create_task(self._run(cmd))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run(self, cmd: list[str]) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()
        except OSError:
            pass


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
