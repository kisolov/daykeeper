"""Row/panel rendering as Rich Text. Lumon palette, monospace, no grouping by kind."""

from datetime import date

from rich.text import Text

from ..stats import fmt_duration

ACCENT = "#6fb8e3"
BRIGHT = "#f2fcff"
MUTED = "#4A6B80"
OK = "#7fc8a9"
WARN = "#e3c26f"
BAD = "#c97a7a"
FG = "#cfe6f2"

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
WIDTH = 50


def human_day(d: date, today: date) -> str:
    label = {0: "СЕГОДНЯ", 1: "ЗАВТРА", -1: "ВЧЕРА"}.get((d - today).days, "ДЕНЬ")
    return f"{label} · {WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def time_span(start: str, end: str) -> str:
    if start.endswith(":00") and end.endswith(":00"):
        return f"{start[:2]}–{end[:2]}"
    return f"{start}–{end}"


def task_meta(task: dict) -> str:
    if task["kind"] == "check":
        return "✓"
    if task["kind"] == "duration":
        return f"⏱ {fmt_duration(task['duration_min'] * 60)} · {task['pomodoros']}🍅"
    return f"{task['pomodoros']}🍅"


def task_row(task: dict, selected: bool, width: int = WIDTH) -> Text:
    row = Text()
    row.append("›" if selected else " ", style=ACCENT)
    if task["running"]:
        row.append("[▶]", style=WARN)
    elif task["done"]:
        row.append("[x]", style=OK)
    else:
        row.append("[ ]")
    row.append(" ")
    if task["kind"] == "timed":
        row.append(time_span(task["start"], task["end"]) + " ", style=ACCENT if selected else MUTED)
    row.append(task["title"], style=MUTED if task["done"] else FG)
    meta = task_meta(task)
    gap = max(2, width - row.cell_len - Text(meta).cell_len)
    row.append(" " * gap)
    row.append(meta, style=MUTED)
    return row


def bar(fraction: float, width: int = 27) -> Text:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return Text.assemble(("█" * filled, ACCENT), ("░" * (width - filled), MUTED))


def clock(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m:02d}:{s:02d}"


def timer_panel(t: dict) -> Text:
    phase = "работа" if t["phase"] == "work" else "отдых"
    out = Text()
    out.append(f"  {t['title']}", style=ACCENT)
    out.append(f"  · помидор {t['pomodoro_no']} из {t['pomodoro_total']} · {phase}", style=MUTED)
    if not t["running"]:
        out.append(" · пауза", style=WARN)
    out.append("\n\n")
    out.append(f"          {clock(t['remaining_s'])}\n", style=f"bold {BRIGHT}")
    done = t["phase_s"] - t["remaining_s"]
    out.append("  ")
    out.append_text(bar(done / t["phase_s"] if t["phase_s"] else 0))
    out.append(f"  {done // 60}/{t['phase_s'] // 60}\n", style=MUTED)
    if t["next"]:
        steps = " → ".join(f"{'работа' if p['kind'] == 'work' else 'отдых'} {p['minutes']}м" for p in t["next"][:2])
        out.append("  дальше: ", style=MUTED)
        out.append(steps)
    return out


def rule(width: int = WIDTH) -> Text:
    return Text("─" * width, style=MUTED)


def keys_hint(pairs: list[tuple[str, str]]) -> Text:
    out = Text()
    for i, (key, label) in enumerate(pairs):
        if i:
            out.append("  ")
        out.append(key, style=MUTED)
        out.append(f" {label}")
    return out
