"""SQLite connection and schema."""

import sqlite3
from pathlib import Path

SCHEMA_V1 = """
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('check','timed','duration')),
    position INTEGER NOT NULL,
    start TEXT, "end" TEXT, duration_min INTEGER,
    tag TEXT,
    habit_id INTEGER REFERENCES habits(id) ON DELETE SET NULL,
    done INTEGER NOT NULL DEFAULT 0,
    done_at TEXT,
    progress_phase INTEGER NOT NULL DEFAULT 0,
    progress_elapsed_s INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX tasks_day ON tasks(day, position);
CREATE TABLE habits (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    weekdays TEXT NOT NULL,
    tag TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE trackers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    unit TEXT
);
CREATE TABLE tracker_entries (
    tracker_id INTEGER NOT NULL REFERENCES trackers(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    value REAL NOT NULL,
    UNIQUE (tracker_id, day)
);
CREATE TABLE goals (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('focus_tag','tracker','count_tag')),
    target REAL NOT NULL,
    created TEXT NOT NULL,
    tag TEXT,
    tracker_id INTEGER REFERENCES trackers(id) ON DELETE CASCADE,
    period TEXT,
    deadline TEXT
);
CREATE TABLE segments (
    id INTEGER PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    day TEXT NOT NULL,
    started TEXT NOT NULL,
    ended TEXT NOT NULL,
    seconds INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX segments_day ON segments(day);
CREATE TABLE days (
    day TEXT PRIMARY KEY,
    spawned INTEGER NOT NULL DEFAULT 0,
    closed INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    summary_seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE timer (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    task_id INTEGER NOT NULL,
    phases_json TEXT NOT NULL,
    phase_index INTEGER NOT NULL,
    phase_elapsed_s INTEGER NOT NULL,
    running INTEGER NOT NULL,
    resumed_at TEXT
);
"""

SCHEMA_V2 = "ALTER TABLE timer ADD COLUMN heartbeat TEXT;"

MIGRATIONS = [SCHEMA_V1, SCHEMA_V2]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = NORMAL")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        con.executescript(script)
        con.execute(f"PRAGMA user_version = {i}")
    con.commit()
    return con
