"""Shared notes by stable id: list, read, create, edit, delete, toggle open."""

from __future__ import annotations

import base64
import json
import secrets
import sqlite3
from datetime import date, datetime, timezone

from festin import log as kitchen_log
from festin.errors import NotFound, StaleState
from festin.schema import NOTE_COLORS, PRIORITIES

PAGE_SIZE = 20
OPEN_NOTE_CAP = 25


def list_notes(conn: sqlite3.Connection, *, q: str = "", cursor: str | None = None, limit: int = PAGE_SIZE) -> dict:
    limit = _page_limit(limit)
    params: list = []
    where = []
    if q:
        needle = f"%{' '.join(q.split()).casefold()}%"
        where.append("(lower(kind) LIKE ? OR lower(text) LIKE ?)")
        params.extend([needle, needle])
    if cursor:
        written, note_id = _decode_cursor(cursor)
        where.append(
            """(
                ifnull(written_on, '') < ?
                OR (ifnull(written_on, '') = ? AND id > ?)
            )"""
        )
        params.extend([written, written, note_id])
    sql = "SELECT * FROM notes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Newest written first; stable id tie-break.
    sql += " ORDER BY ifnull(written_on, '') DESC, id ASC LIMIT ?"
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()
    items = [_public(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["written_on"] or "", last["id"])
    return {"notes": items, "nextCursor": next_cursor}


def get_note(conn: sqlite3.Connection, note_id: str) -> dict:
    return _public(_row(conn, note_id))


def create_note(conn: sqlite3.Connection, body: dict, *, now: datetime | None = None) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    text = str(body.get("text") or "").strip()
    if not text or len(text) > 16000:
        raise ValueError("Write a note under 16,000 characters.")
    kind = _clean_kind(body.get("type", body.get("kind")))
    color = _clean_color(body.get("color"))
    priority = body.get("priority")
    if priority not in (None, *PRIORITIES):
        raise ValueError("Unknown priority")
    leaving_open = bool(body.get("open"))
    if leaving_open and _open_count(conn) >= OPEN_NOTE_CAP:
        raise ValueError("Twenty-five notes are already open. Close one before opening another.")
    instant = now or datetime.now(timezone.utc)
    day = instant.astimezone(timezone.utc).date().isoformat()
    stamp = _stamp(instant)
    note_id = str(body.get("id") or "").strip() or secrets.token_urlsafe(12)
    if conn.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone():
        raise ValueError("That note id is already used.")
    band = _clean_band(body.get("band")) if "band" in body else None
    conn.execute(
        """
        INSERT INTO notes (
            id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            note_id,
            kind,
            text,
            color,
            priority,
            1 if leaving_open else 0,
            day,
            None,
            band,
            stamp,
        ),
    )
    title = " ".join(text.split())
    if len(title) > 80:
        title = title[:79] + "…"
    kitchen_log.record_event(
        conn,
        "note_created",
        ref_id=note_id,
        at=stamp,
        title=title,
        detail=kind,
        extra={"type": kind},
    )
    conn.commit()
    return get_note(conn, note_id)


def edit_note(conn: sqlite3.Connection, note_id: str, body: dict, *, now: datetime | None = None) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, note_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("This note changed. Refresh before editing it.")
    text = row["text"]
    if "text" in body:
        text = str(body.get("text") or "").strip()
        if not text or len(text) > 16000:
            raise ValueError("Write a note under 16,000 characters.")
    kind = _clean_kind(body["type"]) if "type" in body else (_clean_kind(body["kind"]) if "kind" in body else row["kind"])
    color = _clean_color(body["color"]) if "color" in body else row["color"]
    priority = row["priority"]
    if "priority" in body:
        priority = body["priority"]
        if priority not in (None, *PRIORITIES):
            raise ValueError("Unknown priority")
    open_note = bool(row["open"])
    if "open" in body:
        open_note = bool(body["open"])
        if open_note and not row["open"] and _open_count(conn) >= OPEN_NOTE_CAP:
            raise ValueError("Twenty-five notes are already open. Close one before opening another.")
    band = row["band"]
    if "band" in body:
        band = _clean_band(body["band"])
    instant = now or datetime.now(timezone.utc)
    day = instant.astimezone(timezone.utc).date().isoformat()
    stamp = _stamp(instant)
    conn.execute(
        """
        UPDATE notes SET
            kind = ?, text = ?, color = ?, priority = ?, open = ?,
            updated_on = ?, band = ?, updated_at = ?
        WHERE id = ?
        """,
        (kind, text, color, priority, 1 if open_note else 0, day, band, stamp, note_id),
    )
    conn.commit()
    return get_note(conn, note_id)


def delete_note(conn: sqlite3.Connection, note_id: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, note_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("This note changed. Refresh before deleting it.")
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    return {"status": "deleted", "id": note_id}


def toggle_note(conn: sqlite3.Connection, note_id: str, body: dict | None = None, *, now: datetime | None = None) -> dict:
    body = body or {}
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, note_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected is not None and expected != row["updated_at"]:
        raise StaleState("This note changed. Refresh before editing it.")
    opening = not bool(row["open"])
    if opening and _open_count(conn) >= OPEN_NOTE_CAP:
        raise ValueError("Twenty-five notes are already open. Close one before opening another.")
    stamp = _stamp(now)
    conn.execute(
        "UPDATE notes SET open = ?, updated_at = ? WHERE id = ?",
        (1 if opening else 0, stamp, note_id),
    )
    conn.commit()
    return get_note(conn, note_id)


def _row(conn: sqlite3.Connection, note_id: str):
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise NotFound("Unknown note ID.")
    return row


def _open_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM notes WHERE open = 1").fetchone()[0]


def _public(row) -> dict:
    return {
        "id": row["id"],
        "type": row["kind"],
        "text": row["text"],
        "color": row["color"],
        "priority": row["priority"],
        "open": bool(row["open"]),
        "date": row["written_on"],
        "updated": row["updated_on"],
        "band": row["band"],
        "updatedAt": row["updated_at"],
    }


def _clean_kind(value) -> str:
    label = " ".join(str(value or "note").split())
    if not label or len(label) > 40:
        raise ValueError("Give the note a short label, at most 40 characters.")
    return label


def _clean_color(value) -> str:
    color = str(value or "none").strip().casefold()
    if color not in NOTE_COLORS:
        raise ValueError("Choose a Catppuccin accent, or none: " + ", ".join(NOTE_COLORS) + ".")
    return color


def _clean_band(value):
    if value is None or value == "":
        return None
    band = str(value).strip()
    return band or None


def _page_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return PAGE_SIZE
    return min(limit, 100)


def _encode_cursor(written: str, note_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([written, note_id]).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    pad = "=" * (-len(cursor) % 4)
    try:
        written, note_id = json.loads(base64.urlsafe_b64decode(cursor + pad))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Bad cursor") from exc
    if not isinstance(written, str) or not isinstance(note_id, str):
        raise ValueError("Bad cursor")
    return written, note_id


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
