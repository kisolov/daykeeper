"""Дашборд: сегодня, фокус за неделю, цели, привычки, трекеры, мотивация."""

from datetime import date, timedelta

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Static

from ..rpc import DaemonDown
from ..service import ServiceError
from ..stats import fmt_duration
from . import widgets as w

SPARK = "▁▂▃▄▅▆▇█"
COL = 40


def _section(title: str, extra: str = "") -> Text:
    return Text.assemble((title, w.MUTED), (f"  {extra}" if extra else "", w.MUTED), "\n")


def _goal_value(g: dict, value) -> str:
    if value is None:
        return "—"
    if g["kind"] == "focus_tag":
        return fmt_duration(int(value * 3600))
    return f"{value:g}"


def _goal_delta(g: dict) -> str:
    d = g["delta"]
    if g["kind"] == "focus_tag":
        return f"−{fmt_duration(int(abs(d) * 3600))}"
    return f"{d:+.1f}".replace("-", "−")


def _spark(series: list) -> Text:
    values = [v for v in series if v is not None]
    out = Text()
    lo, hi = (min(values), max(values)) if values else (0, 0)
    for v in series:
        if v is None:
            out.append("·", style=w.MUTED)
        else:
            i = 0 if hi == lo else round((v - lo) / (hi - lo) * (len(SPARK) - 1))
            out.append(SPARK[i], style=w.ACCENT)
    return out


class DashboardScreen(Screen):
    AUTO_FOCUS = None
    BINDINGS = [
        Binding("left", "week(-1)", show=False),
        Binding("right", "week(1)", show=False),
        Binding("t", "this_week", show=False),
        Binding("q,escape,d", "back", show=False),
    ]

    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.anchor: date | None = None
        self._plain = ""

    def compose(self) -> ComposeResult:
        yield Static(id="dash-head")
        with Horizontal(id="dash-cols"):
            yield Static(id="dash-left")
            yield Static(id="dash-right")
        yield Static(id="dash-foot")

    def on_mount(self) -> None:
        self.reload()

    def dash_text(self) -> str:
        return self._plain

    def live(self, state: dict) -> None:
        pass

    def reload(self) -> None:
        try:
            data = self.backend.call("dashboard", day=self.anchor.isoformat() if self.anchor else None)
        except DaemonDown as e:
            self._show(Text(str(e), style=w.WARN), Text(), Text(), w.keys_hint([("q", "назад")]))
            return
        except ServiceError as e:
            self.app.notify(e.message, severity="warning")
            return
        if self.anchor is None:
            self.anchor = date.fromisoformat(data["today"]["day"])
        self._show(*self._build(data))

    def _show(self, head: Text, left: Text, right: Text, foot: Text) -> None:
        self.query_one("#dash-head", Static).update(head)
        self.query_one("#dash-left", Static).update(left)
        self.query_one("#dash-right", Static).update(right)
        self.query_one("#dash-foot", Static).update(foot)
        self._plain = "\n".join(t.plain for t in (head, left, right, foot))

    def _build(self, data: dict) -> tuple[Text, Text, Text, Text]:
        d = self.anchor
        head = Text.assemble(("ДАШБОРД", f"bold {w.BRIGHT}"),
                             (f" · неделя {d.isocalendar().week} · {w.WEEKDAYS[d.weekday()]} {d.day} {w.MONTHS[d.month - 1]}", w.MUTED),
                             "\n", ("═" * (COL * 2 + 4), w.MUTED))
        left, right = Text(), Text()

        t = data["today"]
        left.append_text(_section("СЕГОДНЯ"))
        frac = t["done"] / t["total"] if t["total"] else 0
        left.append(f" {t['done']}/{t['total']} задач  ")
        left.append_text(w.bar(frac, 16))
        left.append(f"  {round(frac * 100)}%\n")
        left.append(f" {fmt_duration(t['focus_s'])} фокуса · {t['pomodoros']}🍅\n")
        if t["next_timed"]:
            left.append(" дальше: ")
            left.append(t["next_timed"]["start"], style=w.ACCENT)
            left.append(f" {t['next_timed']['title']}\n")
        left.append("\n")

        if data["goals"]:
            left.append_text(_section("ЦЕЛИ"))
            for g in data["goals"]:
                left.append(f" {g['title']}\n")
                frac = (g["value"] or 0) / g["target"] if g["target"] and g["kind"] != "tracker" else 0
                if g["kind"] == "tracker" and g["start"] is not None and g["value"] is not None and g["start"] != g["target"]:
                    frac = (g["start"] - g["value"]) / (g["start"] - g["target"])
                left.append("   ")
                left.append_text(w.bar(frac, 18))
                left.append(f" {_goal_value(g, g['value'])}")
                if g["behind"]:
                    left.append(f"  {_goal_delta(g)} от темпа", style=w.WARN)
                left.append("\n")
            left.append("\n")

        if data["habits"]:
            left.append_text(_section("ПРИВЫЧКИ", "14 дней"))
            for h in data["habits"]:
                left.append(f" {h['title'][:16]:<16} ")
                for mark in h["grid"]:
                    if mark is None:
                        left.append("·", style=w.MUTED)
                    elif mark:
                        left.append("■", style=w.OK)
                    else:
                        left.append("□", style=w.BAD)
                left.append(f"  🔥{h['streak']}\n", style=w.BRIGHT if h["streak"] else w.MUTED)

        week = data["week"]
        right.append_text(_section("ФОКУС ЗА НЕДЕЛЮ"))
        peak = max((x["focus_s"] for x in week["days"]), default=0) or 1
        for i, x in enumerate(week["days"]):
            n = round(x["focus_s"] / peak * 12)
            right.append(f" {w.WEEKDAYS[i]} ")
            right.append(("█" * n).ljust(12) if n else "·".ljust(12), style=w.ACCENT if n else w.MUTED)
            right.append(f" {fmt_duration(x['focus_s']) if x['focus_s'] else '0'}\n")
        arrow = "▲" if week["total_s"] > week["prev_total_s"] else "▼" if week["total_s"] < week["prev_total_s"] else "="
        right.append(f" итого {fmt_duration(week['total_s'])} · прошлая {fmt_duration(week['prev_total_s'])} ", style=w.MUTED)
        right.append(f"{arrow}\n\n", style=w.OK if arrow == "▲" else w.BAD if arrow == "▼" else w.MUTED)

        if data["trackers"]:
            right.append_text(_section("ТРЕКЕРЫ", "7 дн"))
            for tr in data["trackers"]:
                last = "—" if tr["last"] is None else f"{tr['last']:g}"
                right.append(f" {tr['name'][:8]:<8} {last:>6}{(' ' + tr['unit']) if tr['unit'] else '':<4} ")
                right.append_text(_spark(tr["series"]))
                right.append("\n")

        foot = Text("═" * (COL * 2 + 4) + "\n", style=w.MUTED)
        if data["motivation"]:
            foot.append("» ", style=w.ACCENT)
            foot.append(data["motivation"] + "\n")
        foot.append_text(w.keys_hint([("←/→", "неделя"), ("t", "сегодня"), ("q", "назад")]))
        return head, left, right, foot

    def action_week(self, delta: int) -> None:
        if self.anchor:
            self.anchor += timedelta(weeks=delta)
            self.reload()

    def action_this_week(self) -> None:
        self.anchor = None
        self.reload()

    def action_back(self) -> None:
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()
        else:
            from .today import TodayScreen
            self.app.switch_screen(TodayScreen(self.backend))
