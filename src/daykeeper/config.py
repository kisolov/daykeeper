"""Paths and user config (~/.config/daykeeper/config.toml)."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "daykeeper" / "config.toml"
DATA_DIR = Path.home() / ".local" / "share" / "daykeeper"


def _default_socket() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "daykeeper.sock"


@dataclass
class Config:
    work_min: int = 47
    break_min: int = 13
    db_path: Path = DATA_DIR / "daykeeper.db"
    socket_path: Path = None  # type: ignore[assignment]
    tg_token: str | None = None
    tg_chat_id: int | None = None
    sound: bool = True
    sound_volume: float = 0.4

    def __post_init__(self):
        if self.socket_path is None:
            self.socket_path = _default_socket()


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    raw: dict = {}
    if path.exists():
        raw = tomllib.loads(path.read_text())
    tg = raw.get("telegram", {})
    snd = raw.get("sound", {})
    cfg = Config(
        work_min=int(raw.get("work_min", 47)),
        break_min=int(raw.get("break_min", 13)),
        tg_token=tg.get("token"),
        tg_chat_id=int(tg["chat_id"]) if "chat_id" in tg else None,
        sound=bool(snd.get("enabled", True)),
        sound_volume=float(snd.get("volume", 0.4)),
    )
    if token := os.environ.get("DAYKEEPER_TG_TOKEN"):
        cfg.tg_token = token
    if db := os.environ.get("DAYKEEPER_DB"):
        cfg.db_path = Path(db)
    if sock := os.environ.get("DAYKEEPER_SOCKET"):
        cfg.socket_path = Path(sock)
    return cfg
