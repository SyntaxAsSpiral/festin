"""One-way import from a copy of the live kitchen.

    python -m festin.importer <live-data-dir> <db-path>

Reads babette.json, plans/*.json, and, when the copy has them, recipes.json
and memory.json. The source directory is only opened for reading.

A second run replaces the imported tables with the same rows.

statusPane (the dropped status card) is not stored. Print-job slips stay
where the live file put them: inside a message's extra JSON. Meal plans
come from plans/*.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from festin import settings as core_settings
from festin.schema import NOTE_COLORS, PRIORITIES, WEEKDAYS, apply, connect

PLAN_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
RECIPE_NUMBER = re.compile(r"^CBK-(\d+)$")
WEEKDAY_NUMBER = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
CONTEXT_LANES = ("household", "preferences", "restrictions")
RECIPE_FIELDS = {
    "id",
    "title",
    "kind",
    "category",
    "voice",
    "source",
    "provenance",
    "status",
    "stub",
    "needsPracticeReview",  # live dump only; maps to cooks_before_log, never a column
    "searchDescription",
    "method",
    "notes",
    "context",
    "ocrText",
    "ingredients",
    "appliesTo",
    "tattva",
    "photos",
    "createdAt",
    "updatedAt",
}


def import_directory(
    data_dir: str | Path,
    db_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Load one copy of the live data into the store. Safe to run again.

    `now` is the import instant used to clamp approximate chat dates to the
    household week that contains it. A second run with the same dump and the
    same week writes the same rows.
    """
    root = Path(data_dir)
    state = _read_json(root / "babette.json")
    if not isinstance(state, dict):
        raise ValueError("babette.json must be an object")
    plans = _read_plans(root / "plans")
    recipes = _read_optional(root / "recipes.json")
    memory = _read_optional(root / "memory.json")

    conn = connect(db_path)
    try:
        apply(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            _import_settings(conn, state.get("settings") or {})
            _replace_notes(conn, state.get("journal") or [], memory)
            _replace_plans(conn, plans)
            _replace_chats(conn, state, now=now)
            if recipes is not None:
                _replace_recipes(conn, recipes)
        return _counts(conn)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m festin.importer")
    parser.add_argument("data_dir", help="copy of the live data (babette.json and plans/)")
    parser.add_argument("db_path", help="SQLite database to create or refresh")
    args = parser.parse_args(argv)
    counts = import_directory(args.data_dir, args.db_path)
    for key in ("notes", "weeks", "nights", "ingredients", "chats", "messages", "recipes"):
        print(f"{key}\t{counts[key]}")
    return 0


def _read_json(path: Path):
    """Read one JSON file. The descriptor is read-only."""
    fd = os.open(path, os.O_RDONLY)
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_optional(path: Path):
    if not path.is_file():
        return None
    return _read_json(path)


def _read_plans(directory: Path) -> list[tuple[str, dict]]:
    if not directory.is_dir():
        raise ValueError(f"missing plans directory: {directory}")
    found = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not PLAN_FILE.match(path.name):
            continue
        plan = _read_json(path)
        if not isinstance(plan, dict):
            raise ValueError(f"{path.name} is not a plan object")
        found.append((path.name, plan))
    return found


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _table_name(family) -> str:
    """Live prints and announces the kitchen as settings.family + ' Table'."""
    if family is None:
        return "Babette's Table"
    name = " ".join(str(family).split())
    if not name:
        return "Babette's Table"
    return name + " Table"


def _import_settings(conn: sqlite3.Connection, settings: dict) -> None:
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    dinner = " ".join(str(settings.get("dinner_hour") or "17:30").split()) or "17:30"
    weather = settings.get("weather") if isinstance(settings.get("weather"), dict) else {}
    location = " ".join(str(weather.get("location") or "").split())
    if location:
        label = " ".join(str(weather.get("label") or "").split()) or location
        latitude = _optional_float(weather.get("latitude"))
        longitude = _optional_float(weather.get("longitude"))
        timezone_name = str(weather.get("timezone") or "").strip()
    else:
        label = ""
        latitude = None
        longitude = None
        timezone_name = ""
    base_url = str(settings.get("base_url") or "").strip().rstrip("/") or "https://openrouter.ai/api/v1"
    model_name = " ".join(str(settings.get("model") or "").split())
    conn.execute(
        """
        UPDATE settings SET
            table_name = ?,
            dinner_hour = ?,
            weather_location = ?,
            weather_label = ?,
            weather_latitude = ?,
            weather_longitude = ?,
            weather_timezone = ?,
            model_base_url = ?,
            model_name = ?
        WHERE id = 1
        """,
        (
            _table_name(settings.get("family")),
            dinner,
            location,
            label,
            latitude,
            longitude,
            timezone_name,
            base_url,
            model_name,
        ),
    )
    # Dinner hour lives on the tattva plugin; seed its row (off) from the live copy.
    _seed_tattva_dinner_hour(conn, dinner)


# Stable stamp so a second import of the same copy writes the same plugin row.
_TATTVA_IMPORT_STAMP = "1970-01-01T00:00:00.000000Z"


def _seed_tattva_dinner_hour(conn: sqlite3.Connection, dinner: str) -> None:
    """Write dinnerHour into plugin_settings for tattva without turning the plugin on."""
    from festin.plugins.tattva.compute import clean_dinner_hour

    hour = clean_dinner_hour(dinner)
    row = conn.execute(
        "SELECT enabled, settings_json FROM plugin_settings WHERE plugin_id = ?",
        ("tattva",),
    ).fetchone()
    settings = {"dinnerHour": hour, "sideriodUrl": ""}
    enabled = 0
    if row is not None:
        enabled = 1 if row["enabled"] else 0
        raw = json.loads(row["settings_json"] or "{}")
        if isinstance(raw, dict):
            settings = dict(raw)
            settings["dinnerHour"] = hour
            settings.setdefault("sideriodUrl", "")
    conn.execute(
        """
        INSERT INTO plugin_settings (plugin_id, enabled, settings_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (plugin_id) DO UPDATE SET
            settings_json = excluded.settings_json,
            updated_at = excluded.updated_at
        """,
        (
            "tattva",
            enabled,
            json.dumps(settings, ensure_ascii=False, sort_keys=True),
            _TATTVA_IMPORT_STAMP,
        ),
    )


def _optional_float(value):
    if value is None or value == "":
        return None
    return float(value)


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _replace_notes(conn: sqlite3.Connection, journal, memory) -> None:
    if not isinstance(journal, list):
        raise ValueError("journal must be a list")
    rows = [_note_from_journal(note) for note in journal]
    # Context sections belong in household_context, never in notes.
    rows = [
        row
        for row in rows
        if not (isinstance(row[0], str) and row[0].startswith("context-"))
        and row[1] not in CONTEXT_LANES
    ]
    seen = {row[0] for row in rows}
    if isinstance(memory, dict):
        for row in _notes_from_memory(memory):
            if row[0] not in seen:
                rows.append(row)
                seen.add(row[0])
        _replace_household_context(conn, memory)
    else:
        conn.execute("DELETE FROM household_context")
    conn.execute("DELETE FROM notes")
    conn.executemany(
        """
        INSERT INTO notes (
            id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _replace_household_context(conn: sqlite3.Connection, memory: dict) -> None:
    context = memory.get("context") if isinstance(memory.get("context"), dict) else {}
    if context.get("dietary") and not context.get("restrictions"):
        context = dict(context)
        context["restrictions"] = context.get("dietary")
    conn.execute("DELETE FROM household_context")
    for lane in CONTEXT_LANES:
        text = context.get(lane)
        if not isinstance(text, str) or not text.strip():
            continue
        conn.execute(
            "INSERT INTO household_context (section, text, updated_at) VALUES (?, ?, NULL)",
            (lane, text),
        )


def _note_from_journal(note: dict) -> tuple:
    if not isinstance(note, dict):
        raise ValueError("a journal entry is not an object")
    note_id = note.get("id")
    if not isinstance(note_id, str) or not note_id.strip():
        raise ValueError("a journal note has no stable id")
    if "type" in note:
        kind = note.get("type")
    elif "kind" in note:
        kind = note.get("kind")
    else:
        kind = "note"
    kind = " ".join(str(kind or "note").split()) or "note"
    text = note.get("text") if isinstance(note.get("text"), str) else ""
    color = str(note.get("color") or "none").strip().casefold()
    if color not in NOTE_COLORS:
        color = "none"
    priority = note.get("priority")
    if priority not in PRIORITIES:
        priority = None
    if "open" in note:
        open_note = 1 if note.get("open") else 0
    else:
        open_note = 0 if note.get("done") else 1
    written = _day(note.get("date"))
    updated = _day(note.get("updated"))
    band = _text(note.get("band"))
    return (
        note_id.strip(),
        kind,
        text,
        color,
        priority,
        open_note,
        written,
        updated,
        band,
        updated or written,
    )


def _notes_from_memory(memory: dict) -> list[tuple]:
    rows = []
    dates = memory.get("standingDates") if isinstance(memory.get("standingDates"), dict) else {}
    meta = memory.get("standingMeta") if isinstance(memory.get("standingMeta"), dict) else {}
    standing = memory.get("standing") if isinstance(memory.get("standing"), list) else []
    for raw in standing:
        if not isinstance(raw, str) or not raw.strip():
            continue
        info = meta.get(raw) if isinstance(meta.get(raw), dict) else {}
        priority = info.get("priority")
        if priority not in PRIORITIES:
            priority = None
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        written = _day(dates.get(raw))
        updated = _day(info.get("updated"))
        rows.append(
            (
                f"standing-{digest}",
                "preference",
                raw,
                "none",
                priority,
                0,
                written,
                updated,
                None,
                updated or written,
            )
        )
    requests = memory.get("requests") if isinstance(memory.get("requests"), list) else []
    for req in requests:
        if not isinstance(req, dict):
            continue
        text = req.get("text") if isinstance(req.get("text"), str) else ""
        req_id = req.get("id")
        if not isinstance(req_id, str) or not req_id.strip():
            req_id = "request-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        priority = req.get("priority")
        if priority not in PRIORITIES:
            priority = None
        written = _day(req.get("addedAt"))
        updated = _day(req.get("updated"))
        rows.append(
            (
                req_id.strip(),
                "dinner",
                text,
                "yellow",
                priority,
                0 if req.get("status") == "used" else 1,
                written,
                updated,
                None,
                updated or written,
            )
        )
    rows.sort(key=lambda row: row[0])
    return rows


def _day(value):
    if value is None:
        return None
    text = str(value).strip()
    if len(text) >= 10:
        text = text[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _replace_plans(conn: sqlite3.Connection, plans: list[tuple[str, dict]]) -> None:
    weeks = []
    nights = []
    ingredients = []
    seen_dates = set()
    for name, plan in plans:
        start = plan.get("weekStart")
        if start != name[:-5]:
            raise ValueError(f"{name} weekStart is {start!r}")
        start_date = date.fromisoformat(start)
        days = plan.get("days")
        if not isinstance(days, list) or len(days) != 7:
            raise ValueError(f"{name} needs seven nights")
        labels = [day.get("day") if isinstance(day, dict) else None for day in days]
        if labels != list(WEEKDAYS):
            raise ValueError(f"{name} nights are not Saturday through Friday")
        quote = plan.get("slipQuote")
        if quote is None or quote == "":
            slip_quote = ""
        elif isinstance(quote, str):
            slip_quote = " ".join(quote.split())
        else:
            raise ValueError(f"{name} slipQuote is not text")
        # Live has no separate title; the on-screen heading defaults in the UI.
        slip_title = ""
        notes = plan.get("notes") if isinstance(plan.get("notes"), str) else ""
        plates = plan.get("slipPlates")
        plates_json = _json(plates) if isinstance(plates, dict) else None
        updated = plan.get("updatedAt") if isinstance(plan.get("updatedAt"), str) else None
        weeks.append((start, slip_title, slip_quote, notes, plates_json, updated))
        for index, day in enumerate(days):
            when = start_date + timedelta(days=index)
            if WEEKDAY_NUMBER[day["day"]] != when.weekday():
                raise ValueError(f"{name} {day['day']} is not {when.isoformat()}")
            iso = when.isoformat()
            if iso in seen_dates:
                raise ValueError(f"two plans claim {iso}")
            seen_dates.add(iso)
            recipe_id = _recipe_id(day.get("recipe"))
            title = day.get("title") if isinstance(day.get("title"), str) else ""
            cooked = 1 if day.get("cooked") else 0
            nights.append((iso, start, recipe_id, title, cooked, updated))
            items = day.get("ingredients") or []
            if not isinstance(items, list):
                raise ValueError(f"{name} {iso} ingredients are not a list")
            for position, item in enumerate(items):
                if not isinstance(item, str):
                    raise ValueError(f"{name} {iso} has a non-text ingredient")
                ingredients.append((iso, position, item))
    conn.execute("DELETE FROM night_ingredients")
    conn.execute("DELETE FROM nights")
    conn.execute("DELETE FROM weeks")
    conn.executemany(
        "INSERT INTO weeks (start_date, slip_title, slip_quote, notes, plates_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        weeks,
    )
    conn.executemany(
        """
        INSERT INTO nights (date, week_start, recipe_id, title, cooked, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        nights,
    )
    conn.executemany(
        "INSERT INTO night_ingredients (date, position, text) VALUES (?, ?, ?)",
        ingredients,
    )


def _recipe_id(value):
    """Keep the id as written. Do not fold it through the four-digit parser."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _replace_chats(
    conn: sqlite3.Connection,
    state: dict,
    *,
    now: datetime | None = None,
) -> None:
    filed = state.get("chats") or []
    if not isinstance(filed, list):
        raise ValueError("chats must be a list")
    # Ceiling: start of the household week that contains the import instant.
    # Plans often look ahead, so an unclamped weekStart can land in the future.
    ceiling = core_settings.week_bounds(conn, now=now)[0].isoformat()
    chats = []
    messages = []
    seen = set()
    for ordinal, chat in enumerate(filed):
        if not isinstance(chat, dict):
            raise ValueError("a chat is not an object")
        chat_id = chat.get("id")
        if not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError("a chat has no id")
        chat_id = chat_id.strip()
        if chat_id in seen:
            raise ValueError(f"duplicate chat id {chat_id}")
        seen.add(chat_id)
        title = chat.get("title") if isinstance(chat.get("title"), str) else ""
        raw_messages = chat.get("messages") or []
        created_at, date_approx = _chat_approx_created_at(raw_messages, ceiling=ceiling)
        chats.append((chat_id, title, ordinal, 0, None, created_at, date_approx))
        messages.extend(_message_rows(chat_id, raw_messages))
    active_id = state.get("activeChatId")
    active_messages = state.get("messages") or []
    if isinstance(active_id, str) and active_id.strip():
        active_id = active_id.strip()
        if active_id in seen:
            chats = [
                (c[0], c[1], c[2], 1 if c[0] == active_id else c[3], c[4], c[5], c[6])
                for c in chats
            ]
        else:
            created_at, date_approx = _chat_approx_created_at(active_messages, ceiling=ceiling)
            chats.append(
                (active_id, _active_title(active_messages), None, 1, None, created_at, date_approx)
            )
            messages.extend(_message_rows(active_id, active_messages))
    conn.execute("DELETE FROM chat_messages")
    conn.execute("DELETE FROM chats")
    conn.executemany(
        """
        INSERT INTO chats (
            id, title, ordinal, imported_active, updated_at, created_at, date_approx
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        chats,
    )
    conn.executemany(
        """
        INSERT INTO chat_messages (chat_id, position, role, content, extra_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        messages,
    )


def _chat_approx_created_at(messages, *, ceiling: str) -> tuple[str | None, int]:
    """Earliest plan.weekStart on user messages, clamped to the import week.

    Live chats stored no times. The earliest attached plan week is the best
    signal, but planning ahead can push that into next week — clamp so the
    approximate date is never after the household week that contains import.
    """
    starts = []
    if not isinstance(messages, list):
        return None, 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        plan = message.get("plan")
        if not isinstance(plan, dict):
            continue
        week = plan.get("weekStart")
        if not isinstance(week, str):
            continue
        text = week.strip()
        if len(text) >= 10:
            text = text[:10]
        try:
            date.fromisoformat(text)
        except ValueError:
            continue
        starts.append(text)
    if not starts:
        return None, 0
    earliest = min(starts)
    if earliest > ceiling:
        earliest = ceiling
    return earliest, 1


def _active_title(messages) -> str:
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                line = " ".join(content.split())
                if line:
                    return line[:80]
    return "Current conversation"


def _message_rows(chat_id: str, messages) -> list[tuple]:
    if not isinstance(messages, list):
        raise ValueError(f"chat {chat_id} messages are not a list")
    rows = []
    for position, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"chat {chat_id} has a message that is not an object")
        role = message.get("role") if isinstance(message.get("role"), str) else ""
        content = message.get("content") if isinstance(message.get("content"), str) else ""
        extra = {key: value for key, value in message.items() if key not in ("role", "content")}
        rows.append((chat_id, position, role, content, _json(extra)))
    return rows


def _replace_recipes(conn: sqlite3.Connection, document) -> None:
    if not isinstance(document, dict) or not isinstance(document.get("recipes"), list):
        raise ValueError("recipes.json must be an object with a recipes list")
    rows = []
    numbers = []
    for recipe in document["recipes"]:
        if not isinstance(recipe, dict):
            raise ValueError("a recipe is not an object")
        recipe_id = recipe.get("id")
        if not isinstance(recipe_id, str) or not recipe_id.strip():
            raise ValueError("a recipe has no id")
        recipe_id = recipe_id.strip()
        match = RECIPE_NUMBER.match(recipe_id)
        if match:
            numbers.append(int(match.group(1)))
        kind = "praxis" if recipe.get("kind") == "praxis" else "formule"
        ingredients = recipe.get("ingredients") if isinstance(recipe.get("ingredients"), list) else []
        applies = recipe.get("appliesTo") if isinstance(recipe.get("appliesTo"), list) else []
        # Live dump: praxis used ingredients for the applies-to nouns.
        if kind == "praxis" and not applies and ingredients:
            applies = ingredients
            ingredients = []
        tattva = recipe.get("tattva") if isinstance(recipe.get("tattva"), list) else []
        photos = recipe.get("photos") if isinstance(recipe.get("photos"), list) else []
        extra = {key: value for key, value in recipe.items() if key not in RECIPE_FIELDS}
        category = recipe.get("category") if isinstance(recipe.get("category"), str) else None
        rows.append(
            (
                recipe_id,
                recipe.get("title") if isinstance(recipe.get("title"), str) else "",
                kind,
                category,
                recipe.get("voice") if isinstance(recipe.get("voice"), str) else "",
                recipe.get("source") if isinstance(recipe.get("source"), str) else "",
                _text(recipe.get("provenance")),
                _text(recipe.get("status")),
                1 if recipe.get("stub") else 0,
                # Live flag false means already cooked-or-checked before the log existed.
                0 if recipe.get("needsPracticeReview") else 1,
                recipe.get("searchDescription") if isinstance(recipe.get("searchDescription"), str) else "",
                recipe.get("method") if isinstance(recipe.get("method"), str) else "",
                recipe.get("notes") if isinstance(recipe.get("notes"), str) else "",
                recipe.get("context") if isinstance(recipe.get("context"), str) else "",
                recipe.get("ocrText") if isinstance(recipe.get("ocrText"), str) else "",
                _json(ingredients),
                _json(applies),
                _json(tattva),
                _json(photos),
                _text(recipe.get("createdAt")),
                _text(recipe.get("updatedAt")),
                _json(extra),
            )
        )
    meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    declared = meta.get("nextNumericId")
    declared = declared if isinstance(declared, int) and declared >= 1 else 1
    next_id = max([declared, *(number + 1 for number in numbers)])
    conn.execute("DELETE FROM recipes")
    conn.executemany(
        """
        INSERT INTO recipes (
            id, title, kind, category, voice, source, provenance, status, stub,
            cooks_before_log, search_description, method, notes, context, ocr_text,
            ingredients_json, applies_to_json, tattva_json, photos_json, created_at, updated_at, extra_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.execute("UPDATE catalog_meta SET next_numeric_id = ? WHERE id = 1", (next_id,))
    # A card linked on a slip night has that night as its cook (counted once its week
    # ends); carrying a pre-Log cook as well would count one dinner twice. Same rule as v16.
    conn.execute(
        "UPDATE recipes SET cooks_before_log = 0"
        " WHERE id IN (SELECT recipe_id FROM nights WHERE recipe_id IS NOT NULL AND recipe_id != '')"
    )


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    names = {
        "notes": "notes",
        "weeks": "weeks",
        "nights": "nights",
        "ingredients": "night_ingredients",
        "chats": "chats",
        "messages": "chat_messages",
        "recipes": "recipes",
    }
    return {key: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for key, table in names.items()}


if __name__ == "__main__":
    sys.exit(main())
