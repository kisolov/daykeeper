"""«Сегодня»: one ordered list, timer panel on top while a timer runs."""

from datetime import date, timedelta

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Input, Static

from ..rpc import DaemonDown
from ..service import ServiceError
from ..stats import fmt_duration
from . import widgets as w

EMPTY = "пусто — a добавить или попроси Claude"


class TodayScreen(Screen):
    AUTO_FOCUS = None
    BINDINGS = [
        Binding("up,k", "cursor(-1)", show=False),
        Binding("down,j", "cursor(1)", show=False),
        Binding("home", "cursor_to(0)", show=False),
        Binding("end", "cursor_to(-1)", show=False),
        Binding("space", "toggle_done", show=False),
        Binding("enter", "start", show=False),
        Binding("p", "timer('timer_toggle')", show=False),
        Binding("n", "timer('timer_skip')", show=False),
        Binding("x", "timer('timer_stop')", show=False),
        Binding("J", "move(1)", show=False),
        Binding("K", "move(-1)", show=False),
        Binding("a", "add", show=False),
        Binding("e", "end_day", show=False),
        Binding("left_square_bracket", "shift_day(-1)", show=False),
        Binding("right_square_bracket", "shift_day(1)", show=False),
        Binding("d", "dashboard", show=False),
        Binding("q", "app.quit", show=False),
    ]

    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.day: date | None = None
        self.today: date | None = None
        self.tasks: list[dict] = []
        self.data: dict = {}
        self.timer: dict | None = None
        self.cursor = 0
        self.down = False
        self._shown: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        yield Static(id="timer")
        yield Static(id="list")
        yield Static(id="footer")

    def on_mount(self) -> None:
        self.reload()
        if self.down:
            return
        pending = self._call("summary_pending")
        if pending:
            from .summary import SummaryScreen
            self.app.push_screen(SummaryScreen(pending["day"], pending["summary"]),
                                 lambda _: self._call("summary_seen", day=pending["day"]))

    # --- data ------------------------------------------------------------

    def _call(self, method: str, **params):
        try:
            result = self.backend.call(method, **params)
            self.down = False
            return result
        except DaemonDown as e:
            self.down = True
            self._render_down(str(e))
        except ServiceError as e:
            self.app.notify(e.message, severity="warning")
        return None

    def reload(self) -> None:
        data = self._call("day_get", day=self.day.isoformat() if self.day else None)
        if data is None:
            return
        self.data = data
        self.day = date.fromisoformat(data["day"])
        if self.today is None:
            self.today = self.day
        self.tasks = data["tasks"]
        self.cursor = max(0, min(self.cursor, len(self.tasks) - 1))
        self.timer = self._call("timer_status")
        self._draw()

    def live(self, state: dict) -> None:
        """Push from the daemon: timer ticks and changes made elsewhere."""
        before = (self.data.get("done"), self.data.get("total"), bool(self.timer))
        self.timer = state["timer"]
        if (state["day"]["done"], state["day"]["total"], bool(self.timer)) != before or self.down:
            self.reload()
        else:
            self._render_timer()

    # --- rendering -------------------------------------------------------

    def _put(self, wid: str, content) -> None:
        text = content if isinstance(content, Text) else Text(content)
        self._shown[wid] = text.plain
        self.query_one(f"#{wid}", Static).update(text)

    def header_text(self) -> str:
        return self._shown.get("header", "")

    def timer_text(self) -> str:
        return self._shown.get("timer", "").strip()

    def list_text(self) -> str:
        return self._shown.get("list", "")

    def _render_down(self, message: str) -> None:
        self._put("header", Text(message, style=w.WARN))
        self._put("list", "")
        self._put("timer", "")
        self._put("footer", w.keys_hint([("q", "выйти")]))

    def _render_timer(self) -> None:
        panel = self.query_one("#timer", Static)
        if self.timer:
            self._put("timer", Text.assemble(w.timer_panel(self.timer), "\n", w.rule()))
            panel.display = True
        else:
            self._put("timer", "")
            panel.display = False

    def _draw(self) -> None:
        d = self.data
        left = Text.assemble((w.human_day(self.day, self.today).split(" · ")[0], f"bold {w.BRIGHT}"),
                             (" · " + w.human_day(self.day, self.today).split(" · ")[1], w.MUTED))
        right = f"{d['done']}/{d['total']} · {fmt_duration(d['focus_s'])} фокуса"
        gap = max(2, w.WIDTH - left.cell_len - len(right))
        self._put("header", Text.assemble(left, " " * gap, (right, w.MUTED), "\n", w.rule()))
        self._render_timer()
        if self.tasks:
            rows = Text("\n").join(w.task_row(t, i == self.cursor) for i, t in enumerate(self.tasks))
        else:
            rows = Text(EMPTY, style=w.MUTED)
        self._put("list", rows)
        hints = [("p", "пауза"), ("n", "пропустить"), ("x", "стоп")] if self.timer else [("enter", "таймер")]
        self._put("footer", Text.assemble(
            w.rule(), "\n",
            w.keys_hint([("space", "отметить"), *hints, ("a", "добавить")]), "\n",
            w.keys_hint([("J/K", "переставить"), ("[ ]", "день"), ("e", "завершить день"), ("d", "дашборд"), ("q", "выйти")]),
        ))

    # --- actions ---------------------------------------------------------

    def _current(self) -> dict | None:
        return self.tasks[self.cursor] if self.tasks else None

    def action_cursor(self, delta: int) -> None:
        if self.tasks:
            self.cursor = max(0, min(len(self.tasks) - 1, self.cursor + delta))
            self._draw()

    def action_cursor_to(self, index: int) -> None:
        if self.tasks:
            self.cursor = index % len(self.tasks)
            self._draw()

    def action_toggle_done(self) -> None:
        if task := self._current():
            self._call("task_done", task_id=task["id"], done=not task["done"])
            self.reload()

    def action_start(self) -> None:
        if task := self._current():
            self._call("timer_start", task_id=task["id"])
            self.reload()

    def action_timer(self, method: str) -> None:
        self._call(method)
        self.reload()

    def action_move(self, delta: int) -> None:
        task = self._current()
        if not task:
            return
        target = self.cursor + delta
        if not 0 <= target < len(self.tasks):
            return
        if self._call("task_move", task_id=task["id"], index=target) is not None:
            self.cursor = target
        self.reload()

    def action_add(self) -> None:
        if self.query("#quick") or self.day is None:
            return
        box = Input(placeholder="тренировка 2ч · 09:00-10:00 работа · зубы", id="quick")
        self.mount(box, before=self.query_one("#footer"))
        box.focus()

    def _close_input(self) -> None:
        for box in self.query("#quick"):
            box.remove()
        self.set_focus(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._close_input()
        if event.value.strip():
            added = self._call("task_quick_add", text=event.value, day=self.day.isoformat())
            if added is not None:
                self.reload()
                self.cursor = next((i for i, t in enumerate(self.tasks) if t["id"] == added["id"]), self.cursor)
        self.reload()

    def key_escape(self) -> None:
        self._close_input()

    def action_shift_day(self, delta: int) -> None:
        if self.day:
            self.day += timedelta(days=delta)
            self.cursor = 0
            self.reload()

    def action_end_day(self) -> None:
        summary = self._call("day_close", day=self.day.isoformat())
        if summary is not None:
            from .summary import SummaryScreen
            self.app.push_screen(SummaryScreen(self.day.isoformat(), summary))

    def action_dashboard(self) -> None:
        from .dashboard import DashboardScreen
        self.app.push_screen(DashboardScreen(self.backend))
