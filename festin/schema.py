"""SQLite schema for the shared kitchen.

Plans are nights on real dates, plus a week row for the slip. The week row's
start_date is the plan file's own first day (live files are Saturdays). A
later change to the configured start day regroups those dates; it does not
move a dinner. Recipe ids are text. The live parser accepts at most four
digits; this counter is a plain integer, so CBK-10000 is a legal id.

Schema changes are steps in MIGRATIONS, keyed by PRAGMA user_version.
Append a step. Do not edit an earlier one.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

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

_V1 = """
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

CREATE INDEX IF NOT EXISTS nights_by_recipe ON nights (recipe_id);
CREATE INDEX IF NOT EXISTS nights_by_week ON nights (week_start);
CREATE INDEX IF NOT EXISTS notes_by_kind ON notes (kind);
CREATE INDEX IF NOT EXISTS chats_by_ordinal ON chats (ordinal);
"""


def _version_1(conn: sqlite3.Connection) -> None:
    conn.executescript(_V1)
    conn.executemany(
        "INSERT OR IGNORE INTO note_colors (name) VALUES (?)",
        [(name,) for name in NOTE_COLORS],
    )


def _version_2(conn: sqlite3.Connection) -> None:
    """One row per device. A live turn locks that row's chat, not the process."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            chat_id TEXT,
            turn_json TEXT,
            pane TEXT,
            surface TEXT CHECK (surface IS NULL OR surface IN ('tucked', 'peek', 'full')),
            draft TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


def _version_3(conn: sqlite3.Connection) -> None:
    """Core weather location fields. Geocode fills label/lat/lon/timezone on save."""
    conn.executescript(
        """
        ALTER TABLE settings ADD COLUMN weather_location TEXT NOT NULL DEFAULT '';
        ALTER TABLE settings ADD COLUMN weather_label TEXT NOT NULL DEFAULT '';
        ALTER TABLE settings ADD COLUMN weather_latitude REAL;
        ALTER TABLE settings ADD COLUMN weather_longitude REAL;
        ALTER TABLE settings ADD COLUMN weather_timezone TEXT NOT NULL DEFAULT '';
        """
    )


def _version_4(conn: sqlite3.Connection) -> None:
    """Chat dates. New chats store a real created_at; import may set an approximate week."""
    conn.executescript(
        """
        ALTER TABLE chats ADD COLUMN created_at TEXT;
        ALTER TABLE chats ADD COLUMN date_approx INTEGER NOT NULL DEFAULT 0
            CHECK (date_approx IN (0, 1));
        """
    )


def _version_5(conn: sqlite3.Connection) -> None:
    """BYOK connection fields. The API key stays out of the shared DB."""
    conn.executescript(
        """
        ALTER TABLE settings ADD COLUMN model_base_url TEXT NOT NULL
            DEFAULT 'https://openrouter.ai/api/v1';
        ALTER TABLE settings ADD COLUMN model_name TEXT NOT NULL DEFAULT '';
        """
    )


def _version_6(conn: sqlite3.Connection) -> None:
    """Kitchen Log: recipe/note events going forward, and weather snapshotted on plan save."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kitchen_log_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL
                CHECK (kind IN ('recipe_added', 'recipe_edited', 'note_created')),
            at TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            extra_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS kitchen_log_events_by_at
            ON kitchen_log_events (at DESC, id DESC);

        ALTER TABLE weeks ADD COLUMN weather_json TEXT;
        """
    )


def _version_7(conn: sqlite3.Connection) -> None:
    """Plugin switches and the printer's slip registry (live babette.json 'slips')."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS plugin_settings (
            plugin_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS slips (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            image TEXT NOT NULL,
            rendered_text TEXT NOT NULL DEFAULT '',
            request_key TEXT NOT NULL DEFAULT '',
            signature TEXT NOT NULL DEFAULT '',
            sha256 TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS slips_by_request ON slips (request_key, signature);
        """
    )


def _version_8(conn: sqlite3.Connection) -> None:
    """Shared household favourite flag on recipes."""
    conn.execute(
        """
        ALTER TABLE recipes ADD COLUMN favourite INTEGER NOT NULL DEFAULT 0
            CHECK (favourite IN (0, 1))
        """
    )


def _version_9(conn: sqlite3.Connection) -> None:
    """Widen kitchen_log_events kinds: first cook, archive, favourite, photos."""
    conn.executescript(
        """
        CREATE TABLE kitchen_log_events_v9 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL
                CHECK (kind IN (
                    'recipe_added', 'recipe_edited', 'note_created',
                    'recipe_cooked', 'note_archived', 'recipe_favourited', 'photo_added'
                )),
            at TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            extra_json TEXT NOT NULL DEFAULT '{}'
        );

        INSERT INTO kitchen_log_events_v9
            (id, kind, at, ref_id, title, detail, extra_json)
        SELECT id, kind, at, ref_id, title, detail, extra_json
        FROM kitchen_log_events;

        DROP TABLE kitchen_log_events;
        ALTER TABLE kitchen_log_events_v9 RENAME TO kitchen_log_events;

        CREATE INDEX IF NOT EXISTS kitchen_log_events_by_at
            ON kitchen_log_events (at DESC, id DESC);
        """
    )


def _version_10(conn: sqlite3.Connection) -> None:
    """Split the on-screen slip title from the printed French closing quote."""
    conn.execute(
        "ALTER TABLE weeks ADD COLUMN slip_quote TEXT NOT NULL DEFAULT ''"
    )
    # Imported weeks held Babette's quote in slip_title. A week that only held the
    # default heading (saved from the slip screen) has no quote to carry over.
    conn.execute(
        """
        UPDATE weeks
        SET slip_quote = CASE WHEN lower(trim(slip_title)) = 'le festin' THEN '' ELSE slip_title END,
            slip_title = ''
        """
    )


def _version_11(conn: sqlite3.Connection) -> None:
    """Incoming-recipes inbox: on/off toggle and sha256 of the bearer key."""
    conn.executescript(
        """
        ALTER TABLE settings ADD COLUMN inbox_enabled INTEGER NOT NULL DEFAULT 1
            CHECK (inbox_enabled IN (0, 1));
        ALTER TABLE settings ADD COLUMN inbox_key_hash TEXT NOT NULL DEFAULT '';
        """
    )


def _version_12(conn: sqlite3.Connection) -> None:
    """Chats file with their first message: file every chat that has one, oldest first."""
    rows = conn.execute(
        """
        SELECT id FROM chats
        WHERE ordinal IS NULL
          AND EXISTS (SELECT 1 FROM chat_messages WHERE chat_id = chats.id)
        ORDER BY created_at, id
        """
    ).fetchall()
    for (chat_id,) in rows:
        first = conn.execute(
            "SELECT content FROM chat_messages WHERE chat_id = ? AND role = 'user' ORDER BY position LIMIT 1",
            (chat_id,),
        ).fetchone()
        line = " ".join(str(first[0] or "").split())[:80] if first else ""
        conn.execute(
            """
            UPDATE chats SET
                title = CASE WHEN ? = '' THEN title ELSE ? END,
                ordinal = (SELECT coalesce(max(ordinal), -1) + 1 FROM chats WHERE ordinal IS NOT NULL)
            WHERE id = ?
            """,
            (line, line, chat_id),
        )


def _version_13(conn: sqlite3.Connection) -> None:
    """Household context sections leave the notes table for household_context."""
    conn.executescript(
        """
        CREATE TABLE household_context (
            section TEXT PRIMARY KEY
                CHECK (section IN ('household', 'preferences', 'restrictions')),
            text TEXT NOT NULL DEFAULT '',
            updated_at TEXT
        );
        """
    )
    lanes = ("household", "preferences", "restrictions")
    ids = tuple(f"context-{lane}" for lane in lanes)
    for lane, note_id in zip(lanes, ids):
        row = conn.execute(
            "SELECT text, updated_at FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        if row is None:
            continue
        conn.execute(
            """
            INSERT INTO household_context (section, text, updated_at)
            VALUES (?, ?, ?)
            """,
            (lane, row["text"] or "", row["updated_at"]),
        )
    conn.execute(
        f"DELETE FROM kitchen_log_events WHERE ref_id IN ({','.join('?' * len(ids))})",
        ids,
    )
    conn.execute(
        f"DELETE FROM notes WHERE id IN ({','.join('?' * len(ids))})",
        ids,
    )


# Version n is MIGRATIONS[n - 1]. user_version 0 runs every step.
# v6 is the Kitchen Log. Plugin tables are v7. Shared favourites are v8.
# v9 widens the kitchen log event kinds CHECK.
# v10 splits weeks.slip_quote from weeks.slip_title.
# v11 is the incoming-recipes inbox toggle and key hash.
# v12 files every chat that has a message (chats now file with their first).
# v13 moves household context sections out of notes into household_context.
MIGRATIONS = (
    _version_1,
    _version_2,
    _version_3,
    _version_4,
    _version_5,
    _version_6,
    _version_7,
    _version_8,
    _version_9,
    _version_10,
    _version_11,
    _version_12,
    _version_13,
)

SCHEMA_VERSION = len(MIGRATIONS)


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the store with foreign keys on. The file is created if missing."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply(conn: sqlite3.Connection) -> None:
    """Run any migration newer than this file. A second call changes nothing."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"database schema v{current} is newer than this code (v{SCHEMA_VERSION})")
    for version, step in enumerate(MIGRATIONS, start=1):
        if version <= current:
            continue
        step(conn)
        conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
