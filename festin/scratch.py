"""Babette's private scratch: one string, this kitchen week only.

The household never sees it. set_scratch replaces the whole text. A new chat
reads it as your_scratch. A scratch written in an earlier kitchen week is
empty, and that read clears it. There is no Saturday job.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from festin.chat.schemas import SCRATCH_LIMIT
from festin.settings import get_settings, today as household_today, week_start_for


def collapse(value: str) -> str:
    """Live notesToSelf rule: whitespace runs become a single space."""
    return " ".join(value.split())


def set_scratch(args: dict, ctx: Any) -> dict:
    """Replace the scratch. An empty string clears it. The text is not returned."""
    if not isinstance(args, dict) or "text" not in args:
        raise ValueError("Pass text, or an empty string to clear the scratch.")
    raw = args.get("text")
    if not isinstance(raw, str):
        raise ValueError("Scratch text must be a string.")
    text = collapse(raw)
    if len(text) > SCRATCH_LIMIT:
        raise ValueError(
            f"The private scratch must stay within {SCRATCH_LIMIT} characters."
        )
    conn = _ctx_get(ctx, "conn")
    if not text:
        conn.execute("DELETE FROM babette_scratch WHERE id = 1")
        conn.commit()
        return {"status": "cleared"}
    week = _week_start(conn, ctx).isoformat()
    conn.execute(
        """
        INSERT INTO babette_scratch (id, text, week_start, updated_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            text = excluded.text,
            week_start = excluded.week_start,
            updated_at = excluded.updated_at
        """,
        (text, week, _stamp(_ctx_get(ctx, "now"))),
    )
    conn.commit()
    return {"status": "saved"}


def opening_scratch(conn: sqlite3.Connection, on: date | None = None) -> str:
    """Text for a new chat, or empty. An earlier kitchen week is cleared here."""
    row = conn.execute(
        "SELECT text, week_start FROM babette_scratch WHERE id = 1"
    ).fetchone()
    if row is None:
        return ""
    text = row["text"] or ""
    if not text:
        return ""
    current = _week_start(conn, None, on=on)
    written = _parse_date(row["week_start"])
    if written is None or written < current:
        conn.execute("DELETE FROM babette_scratch WHERE id = 1")
        conn.commit()
        return ""
    return text


def _week_start(conn: sqlite3.Connection, ctx: Any, *, on: date | None = None) -> date:
    if on is None:
        on = _kitchen_day(conn, ctx)
    return week_start_for(on, get_settings(conn)["week_start_day"])


def _kitchen_day(conn: sqlite3.Connection, ctx: Any) -> date:
    """ctx.today when a tool call carries one; otherwise the household date."""
    value = _ctx_get(ctx, "today") if ctx is not None else None
    if isinstance(value, date):
        return value
    now = _ctx_get(ctx, "now") if ctx is not None else None
    if isinstance(now, datetime):
        return household_today(conn, now=now)
    return household_today(conn)


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _ctx_get(ctx: Any, key: str, default=None):
    if ctx is None:
        return default
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def _stamp(now) -> str:
    instant = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
