"""Waybar custom module: one JSON line per state change (continuous `exec`, no interval)."""

import asyncio
import json
import sys

from .rpc import Client, DaemonDown

ACCENT = "#6fb8e3"
MUTED = "#4A6B80"


def _word(word: str, color: str = ACCENT) -> str:
    return f"<span color='{color}'>{word[0]}</span>{word[1:]}"


def _clock(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m:02d}:{s:02d}"


def render(state: dict | None) -> dict:
    if state is None:
        return {"text": f"{_word('day', MUTED)} —", "class": ["down"], "alt": "down",
                "tooltip": "демон не запущен (systemctl --user start daykeeper)"}
    t = state.get("timer")
    day = state["day"]
    if t:
        word = "focus" if t["phase"] == "work" else "brk"
        kind = "work" if t["phase"] == "work" else "break"
        color = ACCENT if t["running"] else MUTED
        classes = [kind] if t["running"] else [kind, "paused"]
        lines = [t["title"], f"помидор {t['pomodoro_no']} из {t['pomodoro_total']}"]
        if t["next"]:
            nxt = t["next"][0]
            lines.append(f"дальше: {'работа' if nxt['kind'] == 'work' else 'отдых'} {nxt['minutes']}м")
        if not t["running"]:
            lines.append("на паузе")
        return {"text": f"{_word(word, color)} {_clock(t['remaining_s'])}", "class": classes,
                "alt": kind if t["running"] else f"{kind}-paused", "tooltip": "\n".join(lines)}
    nxt = day.get("next_timed")
    tooltip = f"сделано {day['done']} из {day['total']}"
    if nxt:
        return {"text": f"{_word('next')} {nxt['start']}", "class": ["idle"], "alt": "idle",
                "tooltip": f"{nxt['start']} — {nxt['title']}\n{tooltip}"}
    return {"text": f"{_word('day')} {day['done']}/{day['total']}", "class": ["idle"], "alt": "idle", "tooltip": tooltip}


def _emit(obj: dict, out) -> None:
    out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    out.flush()


async def stream(client: Client, out=sys.stdout) -> None:
    last = None
    while True:
        try:
            async for state in client.subscribe():
                line = render(state)
                if line != last:
                    _emit(line, out)
                    last = line
        except (DaemonDown, ConnectionError, OSError):
            pass
        down = render(None)
        if down != last:
            _emit(down, out)
            last = down
        await asyncio.sleep(2)
