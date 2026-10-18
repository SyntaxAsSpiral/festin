"""SQLite schema for the shared kitchen.

Plans are nights on real dates, plus a week row for the slip. The week row's
start_date is the plan file's own first day (live files are Saturdays). A
later change to the configured start day regroups those dates; it does not
move a dinner. Recipe ids are text with no numeric ceiling: live ids already
pass CBK-9999, and the catalog counter is a plain integer.

Sessions, plugin settings, and the weather cache are here so the other
backend beads have a place to write. This module does not fill them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

# Catppuccin accents, plus none. Shared by every device. §9 decision 15.
NOTE_COLORS = (
    "rosewater",
    "flamingo",
    "pink",
    "mauve",
    "red",
    "maroon",
    "peach",
    "yellow",
    "green",
    "teal",
    "sky",
    "sapphire",
    "blue",
    "lavender",
    "none",
)

# Live plan files name days this way, Saturday first.
WEEKDAYS = ("sat", "sun", "mon", "tue", "wed", "thu", "fri")

PRIORITIES = ("high", "normal", "low")

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS note_colors (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    table_name TEXT NOT NULL DEFAULT 'Babette''s Table',
    -- Which weekday a rendered week starts on. Dinners stay on their dates.
    week_start_day TEXT NOT NULL DEFAULT 'sat'
        CHECK (week_start_day IN ('sat', 'sun', 'mon', 'tue', 'wed', 'thu', 'fri')),
    dinner_hour TEXT NOT NULL DEFAULT '17:30',
    weather_location TEXT NOT NULL DEFAULT '',
    weather_label TEXT NOT NULL DEFAULT '',
    latitude REAL,
    longitude REAL,
    timezone TEXT,
    weather_fetched_at TEXT,
    forecast_json TEXT,
    model_base_url TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    tts_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT
);

INSERT OR IGNORE INTO settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS catalog_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    -- Next CBK number. Unbounded; 10000 is a legal value.
    next_numeric_id INTEGER NOT NULL DEFAULT 1 CHECK (next_numeric_id >= 1)
);

INSERT OR IGNORE INTO catalog_meta (id) VALUES (1);

CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'recipe' CHECK (kind IN ('recipe', 'praxis')),
    category TEXT,
    voice TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    provenance TEXT,
    status TEXT,
    stub INTEGER NOT NULL DEFAULT 0 CHECK (stub IN (0, 1)),
    needs_practice_review INTEGER NOT NULL DEFAULT 0
        CHECK (needs_practice_review IN (0, 1)),
    search_description TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    ingredients_json TEXT NOT NULL DEFAULT '[]',
    tattva_json TEXT NOT NULL DEFAULT '[]',
    photos_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT,
    extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    -- Live journal "type". Includes preference, and the context lanes when imported.
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT 'none' REFERENCES note_colors (name),
    priority TEXT CHECK (priority IS NULL OR priority IN ('high', 'normal', 'low')),
    open INTEGER NOT NULL CHECK (open IN (0, 1)),
    written_on TEXT,
    updated_on TEXT,
    band TEXT,
    updated_at TEXT
);

-- One row per plan file. start_date is a real calendar date.
CREATE TABLE IF NOT EXISTS weeks (
    start_date TEXT PRIMARY KEY,
    -- slipQuote lands here, in full. The slip editor's 40-character cap is a UI limit.
    slip_title TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    plates_json TEXT,
    updated_at TEXT
);

-- One dinner per calendar date. cooked is new; the live files have no such field.
CREATE TABLE IF NOT EXISTS nights (
    date TEXT PRIMARY KEY,
    week_start TEXT NOT NULL REFERENCES weeks (start_date),
    recipe_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    cooked INTEGER NOT NULL DEFAULT 0 CHECK (cooked IN (0, 1)),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS night_ingredients (
    date TEXT NOT NULL REFERENCES nights (date) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (date, position)
);

CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    -- Order in the live filed list. Null for the unfiled active thread.
    ordinal INTEGER,
    imported_active INTEGER NOT NULL DEFAULT 0 CHECK (imported_active IN (0, 1)),
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    chat_id TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    -- photos, plan, slips, trace, tool results, and anything else on the message.
    extra_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (chat_id, position)
);

-- Per-device cookie session. Empty until the session bead writes it.
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    chat_id TEXT REFERENCES chats (id) ON DELETE SET NULL,
    draft TEXT NOT NULL DEFAULT '',
    pane TEXT,
    chat_surface TEXT,
    drawer_height REAL,
    rail_width REAL,
    composer_height REAL,
    motion INTEGER CHECK (motion IS NULL OR motion IN (0, 1)),
    settings_tab TEXT,
    list_layouts_json TEXT NOT NULL DEFAULT '{}',
    turn_json TEXT,
    lock_chat_id TEXT
);

CREATE TABLE IF NOT EXISTS plugin_settings (
    plugin_id TEXT PRIMARY KEY,
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS nights_by_recipe ON nights (recipe_id);
CREATE INDEX IF NOT EXISTS nights_by_week ON nights (week_start);
CREATE INDEX IF NOT EXISTS notes_by_kind ON notes (kind);
CREATE INDEX IF NOT EXISTS chats_by_ordinal ON chats (ordinal);

PRAGMA user_version = 1;
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the store with foreign keys on. The file is created if missing."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply(conn: sqlite3.Connection) -> None:
    """Create the store if needed. Safe to run on a database that already has it."""
    conn.executescript(SCHEMA)
    for name in NOTE_COLORS:
        conn.execute("INSERT OR IGNORE INTO note_colors (name) VALUES (?)", (name,))
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"database schema v{current} is newer than this code (v{SCHEMA_VERSION})")
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
