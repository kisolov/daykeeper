"""Сводка дня — after «завершить день» or once for an auto-closed day."""

from datetime import date

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static

from ..stats import fmt_duration
from . import widgets as w


class SummaryScreen(Screen):
    BINDINGS = [Binding(w.keys("q,escape,enter"), "close", show=False)]

    def __init__(self, day: str, summary: dict):
        super().__init__()
        self.day = date.fromisoformat(day)
        self.summary = summary

    def compose(self) -> ComposeResult:
        yield Static(self._text(), id="summary")

    def body_text(self) -> str:
        return self._text().plain

    def _text(self) -> Text:
        s = self.summary
        d = self.day
        out = Text()
        out.append("СВОДКА", style=f"bold {w.BRIGHT}")
        out.append(f" · {w.WEEKDAYS[d.weekday()]} {d.day} {w.MONTHS[d.month - 1]}\n", style=w.MUTED)
        out.append_text(w.rule())
        out.append(f"\n{fmt_duration(s['focus_s'])} фокуса · {s['pomodoros']}{w.POMODORO} · "
                   f"сделано {len(s['done'])} из {len(s['done']) + len(s['not_done'])}\n\n")
        out.append("сделано\n", style=w.MUTED)
        for title in s["done"]:
            out.append(" [x] ", style=w.OK)
            out.append(f"{title}\n")
        if not s["done"]:
            out.append(" —\n", style=w.MUTED)
        out.append("\nне сделано\n", style=w.MUTED)
        for title in s["not_done"]:
            out.append(f" [ ] {title}\n")
        if not s["not_done"]:
            out.append(" — всё сделано\n", style=w.OK)
        if s["habits"]:
            out.append("\nпривычки\n", style=w.MUTED)
            for h in s["habits"]:
                out.append(" ■ " if h["done"] else " □ ", style=w.OK if h["done"] else w.BAD)
                out.append(f"{h['title']}")
                out.append(f"  {w.FIRE}{h['streak']}\n" if h["streak"] else "\n", style=w.BRIGHT)
        goals = [g for g in s["goals"] if g["value"] is not None]
        if goals:
            out.append("\nцели\n", style=w.MUTED)
            for g in goals:
                out.append(f" {g['title']}: {g['value']:g} из {g['target']:g}")
                if g["behind"]:
                    out.append("  отстаёшь от темпа", style=w.WARN)
                out.append("\n")
        if s.get("motivation"):
            out.append("\n» ", style=w.ACCENT)
            out.append(f"{s['motivation']}\n")
        out.append_text(w.rule())
        out.append("\n")
        out.append_text(w.keys_hint([("q", "закрыть")]))
        return out

    def action_close(self) -> None:
        self.dismiss(None)
