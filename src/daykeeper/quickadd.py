"""Parse one-line quick add: `09:00-10:00 работа`, `тренировка 2ч`, `код 1ч30м`, `зубы`."""

import re
from datetime import time

_TIMED = re.compile(r"^(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})(?:\s+(.*))?$")
_STRAY_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
_DURATION = re.compile(r"^(?:(.*?)\s+)?(?:(\d+)\s*ч)?\s*(?:(\d+)\s*м)?$")


def _hm(h: str, m: str) -> time:
    hour, minute = int(h), int(m)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"нет такого времени: {h}:{m}")
    return time(hour, minute)


def _result(title, kind, start=None, end=None, duration_min=None) -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("у задачи нет названия")
    return {"title": title, "kind": kind, "start": start, "end": end, "duration_min": duration_min}


def parse_quick_add(text: str) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("пустая строка")
    if m := _TIMED.match(text):
        start, end = _hm(m[1], m[2]), _hm(m[3], m[4])
        if end <= start:
            raise ValueError("конец раньше начала")
        return _result(m[5], "timed", start=start, end=end)
    if _STRAY_TIME.search(text):
        raise ValueError("время задаётся интервалом в начале: 09:00-10:00 встреча")
    m = _DURATION.match(text)
    if m and (m[2] or m[3]):
        minutes = int(m[2] or 0) * 60 + int(m[3] or 0)
        if minutes <= 0:
            raise ValueError("длительность должна быть больше нуля")
        return _result(m[1], "duration", duration_min=minutes)
    return _result(text, "check")
