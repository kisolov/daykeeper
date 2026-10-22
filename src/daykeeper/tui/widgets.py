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

# Nerd Font glyphs (single cell in "JetBrainsMono Nerd Font Mono"); no emoji font is assumed.
POMODORO = ""  # pomicons: pomodoro
TIMER = "\U000f051b"  # md: timer_outline
FIRE = "\U000f0238"  # md: fire

WEEKDAYS =["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
WIDTH = 50
SCREEN_CHROME = 5  # Screen padding (2 + 2) and the reserved scrollbar column (lumon.tcss)


def usable_width(app_width: int, floor: int) -> int:
    """Columns available to content inside a Screen of an `app_width`-wide terminal."""
    return max(floor, app_width - SCREEN_CHROME)


# Same physical key on the ЙЦУКЕН layout, so bindings keep working while Russian is active.
_RU = dict(zip("qwertyuiopasdfghjklzxcvbnm", "йцукенгшщзфывапролдячсмить"))
_RU_NAMED = {"left_square_bracket": "х", "right_square_bracket": "ъ"}


def keys(spec: str) -> str:
    """Binding key list plus the Russian-layout twin of every letter/bracket key in it."""
    out = []
    for key in spec.split(","):
        out.append(key)
        if key in _RU_NAMED:
            out.append(_RU_NAMED[key])
        elif len(key) == 1 and key.lower() in _RU:
            twin = _RU[key.lower()]
            out.append(twin.upper() if key.isupper() else twin)
    return ",".join(out)


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
        return f"{TIMER} {fmt_duration(task['duration_min'] * 60)} · {task['pomodoros']}{POMODORO}"
    return f"{task['pomodoros']}{POMODORO}"


def fit(text: str, cells: int) -> str:
    """Cut to at most `cells` terminal cells, ending with … when cut."""
    t = Text(text)
    if t.cell_len <= cells:
        return text
    t.truncate(max(1, cells), overflow="ellipsis")
    return t.plain


def task_row(task: dict, selected: bool, width: int = WIDTH) -> Text:
    """Exactly `width` cells: marker, optional time, title (cut with …), meta pinned right."""
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
    meta = task_meta(task)
    meta_len = Text(meta).cell_len
    room = width - row.cell_len - meta_len - 2
    row.append(fit(task["title"], room), style=MUTED if task["done"] else FG)
    row.append(" " * max(2, width - row.cell_len - meta_len))
    row.append(meta, style=MUTED)
    return row


def bar(fraction: float, width: int = 27) -> Text:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return Text.assemble(("█" * filled, ACCENT), ("░" * (width - filled), MUTED))


def clock(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m:02d}:{s:02d}"


def timer_panel(t: dict, width: int = WIDTH) -> Text:
    phase = "работа" if t["phase"] == "work" else "отдых"
    info = f"  · помидор {t['pomodoro_no']} из {t['pomodoro_total']} · {phase}" + ("" if t["running"] else " · пауза")
    out = Text()
    out.append("  " + fit(t["title"], max(8, width - Text(info).cell_len - 2)), style=ACCENT)
    out.append(info.replace(" · пауза", ""), style=MUTED)
    if not t["running"]:
        out.append(" · пауза", style=WARN)
    out.append("\n\n")
    out.append(" " * max(0, (width - 5) // 2) + f"{clock(t['remaining_s'])}\n", style=f"bold {BRIGHT}")
    done = t["phase_s"] - t["remaining_s"]
    out.append("  ")
    out.append_text(bar(done / t["phase_s"] if t["phase_s"] else 0, max(10, min(60, width - 12))))
    out.append(f"  {done // 60}/{t['phase_s'] // 60}\n", style=MUTED)
    if t["next"]:
        steps = " → ".join(f"{'работа' if p['kind'] == 'work' else 'отдых'} {p['minutes']}м" for p in t["next"][:2])
        out.append("  дальше: ", style=MUTED)
        out.append(steps)
    return out


def rule(width: int = WIDTH) -> Text:
    return Text("─" * width, style=MUTED)


def keys_hint(pairs: list[tuple[str, str]], width: int | None = None) -> Text:
    """`key label` pairs separated by two spaces, wrapped between pairs to fit `width`."""
    out = Text()
    line_len = 0
    for key, label in pairs:
        item = Text.assemble((key, MUTED), f" {label}")
        if line_len:
            if width is not None and line_len + 2 + item.cell_len > width:
                out.append("\n")
                line_len = 0
            else:
                out.append("  ")
                line_len += 2
        out.append_text(item)
        line_len += item.cell_len
    return out
