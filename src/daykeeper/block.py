"""Site block (Instagram, YouTube, ...): unlock on a typed random code, for a fixed time, a few times a day.

daykeeper owns the procedure — the code, the daily limit, the relock deadline. The network side is a tiny
root helper (contrib/netblock) that only flips the block in sing-box; the daemon calls it via `sudo -n`.
"""

import logging
import secrets
import sqlite3
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from .config import Config

log = logging.getLogger("daykeeper")

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: retyping, not squinting
CHALLENGE_TTL = timedelta(minutes=10)
RETRY_AFTER = timedelta(seconds=30)


class BlockError(ValueError):
    """User-facing refusal; Service turns ValueError into an `invalid` error."""


class NetError(Exception):
    pass


class Net(Protocol):
    def set_blocked(self, blocked: bool) -> None: ...


class SudoHelper:
    """Runs the root helper: `sudo -n <helper> lock|unlock` (NOPASSWD in sudoers)."""

    def __init__(self, helper: str):
        self.helper = helper

    def set_blocked(self, blocked: bool) -> None:
        cmd = ["sudo", "-n", self.helper, "lock" if blocked else "unlock"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise NetError(str(e))
        if r.returncode != 0:
            raise NetError((r.stderr or r.stdout).strip() or f"код {r.returncode}")


def _ts(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Block:
    def __init__(self, con: sqlite3.Connection, cfg: Config, clock: Callable[[], datetime], net: Net):
        self.con = con
        self.cfg = cfg
        self.clock = clock
        self.net = net
        self._pending: tuple[str, datetime] | None = None
        self._retry_at: datetime | None = None

    # --- state -----------------------------------------------------------

    def _open_row(self):
        """The unlock that has not been relocked yet (expired or not)."""
        return self.con.execute(
            "SELECT id, until FROM block_unlocks WHERE relocked = 0 ORDER BY id DESC LIMIT 1").fetchone()

    def _active_until(self) -> datetime | None:
        row = self._open_row()
        if row is None:
            return None
        until = datetime.fromisoformat(row["until"])
        return until if until > self.clock() else None

    def _used_today(self) -> int:
        day = self.clock().date().isoformat()
        return self.con.execute(
            "SELECT count(*) FROM block_unlocks WHERE substr(started, 1, 10) = ?", (day,)).fetchone()[0]

    def status(self) -> dict:
        until = self._active_until()
        return {
            "blocked": until is None, "until": f"{until:%H:%M}" if until else None,
            "used_today": self._used_today(), "daily_limit": self.cfg.block_daily_limit,
            "minutes": self.cfg.block_minutes,
        }

    # --- procedure -------------------------------------------------------

    def challenge(self) -> dict:
        if until := self._active_until():
            raise BlockError(f"уже разблокировано до {until:%H:%M}")
        used, limit = self._used_today(), self.cfg.block_daily_limit
        if used >= limit:
            raise BlockError(f"лимит разблокировок на сегодня исчерпан ({used}/{limit})")
        code = "".join(secrets.choice(ALPHABET) for _ in range(self.cfg.block_code_len))
        self._pending = (code, self.clock() + CHALLENGE_TTL)
        grouped = " ".join(code[i:i + 8] for i in range(0, len(code), 8))
        return {"code": grouped, "expires_min": int(CHALLENGE_TTL.total_seconds() // 60),
                "minutes": self.cfg.block_minutes, "used_today": used, "daily_limit": limit}

    def unlock(self, code: str) -> dict:
        if self._pending is None:
            raise BlockError("сначала запроси код (block_challenge)")
        expected, expires = self._pending
        self._pending = None
        if self.clock() > expires:
            raise BlockError("код устарел, запроси новый")
        if "".join(code.split()).lower() != expected:
            raise BlockError("код неверный, запроси новый")
        try:
            self.net.set_blocked(False)
        except NetError as e:
            raise BlockError(f"не удалось открыть сеть: {e}")
        now = self.clock()
        self.con.execute("UPDATE block_unlocks SET relocked = 1 WHERE relocked = 0")
        self.con.execute("INSERT INTO block_unlocks (started, until) VALUES (?, ?)",
                         (_ts(now), _ts(now + timedelta(minutes=self.cfg.block_minutes))))
        self.con.commit()
        return self.status()

    def lock(self) -> dict:
        try:
            self.net.set_blocked(True)
        except NetError as e:
            raise BlockError(f"не удалось закрыть сеть: {e}")
        self._close_open(self.clock())
        return self.status()

    def _close_open(self, now: datetime) -> None:
        row = self._open_row()
        if row is None:
            return
        until = min(datetime.fromisoformat(row["until"]), now)
        self.con.execute("UPDATE block_unlocks SET relocked = 1, until = ? WHERE id = ?", (_ts(until), row["id"]))
        self.con.commit()
        self._retry_at = None

    # --- daemon hooks ----------------------------------------------------

    def tick(self) -> bool:
        """Relock once the unlock is over. True when the block came back."""
        row = self._open_row()
        if row is None:
            return False
        now = self.clock()
        if datetime.fromisoformat(row["until"]) > now:
            return False
        if self._retry_at and now < self._retry_at:
            return False
        try:
            self.net.set_blocked(True)
        except NetError as e:
            log.warning("relock failed: %s", e)
            self._retry_at = now + RETRY_AFTER
            return False
        self._close_open(now)
        return True

    def enforce(self) -> None:
        """Daemon start: make the network match the stored state (boot always comes up blocked)."""
        try:
            if self._active_until():
                self.net.set_blocked(False)
            else:
                self.net.set_blocked(True)
                self._close_open(self.clock())
        except NetError as e:
            log.warning("block enforce failed: %s", e)
