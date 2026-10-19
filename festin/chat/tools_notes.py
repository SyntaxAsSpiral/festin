"""Note tools over the SQLite notes table (journal, preference, context lanes)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import date
from typing import Any

from festin import log as kitchen_log
from festin.chat.schemas import (
    CONTEXT_LANES,
    CONTEXT_LIMITS,
    NOTE_COLOR_CHOICES,
    OPEN_NOTE_CAP,
)
from festin.chat.tools_recipes import ctx_get, ctx_today, stamp_now
from festin.schema import NOTE_COLORS, PRIORITIES


def _clean_kind(value) -> str:
    label = " ".join(str(value or "note").split())
    if not label or len(label) > 40:
        raise ValueError("Give the note a short label, at most 40 characters.")
    return label


def _clean_color(value) -> str:
    color = str(value or "none").strip().casefold()
    if color not in NOTE_COLOR_CHOICES:
        raise ValueError(
            "Choose a Catppuccin accent, or none: " + ", ".join(c for c in NOTE_COLORS if c != "none") + "."
        )
    return color


def _clean_band(value) -> str | None:
    band = str(value or "").strip()
    return band or None


def _open_count(conn) -> int:
    return conn.execute(
        """
        SELECT count(*) FROM notes
        WHERE open = 1 AND kind NOT IN ('preference', 'household', 'preferences', 'restrictions')
        """
    ).fetchone()[0]


def note_for_model(row, today: date) -> dict:
    written = str(row["written_on"] or "")[:10] or None
    updated = str(row["updated_on"] or written or "")[:10] or None
    priority = row["priority"] if row["priority"] in PRIORITIES else "normal"

    def age(value):
        if not value:
            return None
        try:
            return (today - date.fromisoformat(value)).days
        except ValueError:
            return None

    open_note = bool(row["open"])
    kind = row["kind"]
    note = {
        "type": kind,
        "text": row["text"] or "",
        "open": open_note,
        "done": not open_note,
        "priority": priority,
        "written": written,
        "updated": updated,
        "age_days": age(written),
        "days_since_update": age(updated),
    }
    if row["color"] in NOTE_COLOR_CHOICES:
        note["color"] = row["color"]
    if row["band"]:
        note["band"] = row["band"]
    if row["id"]:
        note["id"] = row["id"]
    if kind in CONTEXT_LANES:
        note["context"] = kind
    return note


def all_notes(conn, today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = conn.execute("SELECT * FROM notes").fetchall()
    # Context lanes first in a stable order, then the rest.
    by_id = {row["id"]: row for row in rows}
    notes = []
    for lane in CONTEXT_LANES:
        row = by_id.get(f"context-{lane}")
        if row is None:
            notes.append(
                note_for_model(
                    {
                        "id": f"context-{lane}",
                        "kind": lane,
                        "text": "",
                        "color": "none",
                        "priority": None,
                        "open": 0,
                        "written_on": None,
                        "updated_on": None,
                        "band": None,
                    },
                    today,
                )
            )
        else:
            notes.append(note_for_model(row, today))
    for row in rows:
        if row["id"] in {f"context-{lane}" for lane in CONTEXT_LANES}:
            continue
        notes.append(note_for_model(row, today))
    return notes


def _context_text(conn, lane: str) -> str:
    row = conn.execute("SELECT text FROM notes WHERE id = ?", (f"context-{lane}",)).fetchone()
    return row["text"] if row else ""


def save_context(args: dict, ctx: Any) -> dict:
    name = args.get("context")
    if name not in CONTEXT_LANES:
        raise ValueError("Choose household, preferences, or restrictions.")
    text = str(args.get("text") or "").strip()
    conn = ctx_get(ctx, "conn")
    cards = {lane: _context_text(conn, lane) for lane in CONTEXT_LANES}
    if name == "restrictions" and args.get("append"):
        current = cards.get(name, "")
        if text and text.casefold() not in current.casefold():
            text = (current + ("\n" if current else "") + text).strip()
        else:
            text = current
    elif "original" in args and cards.get(name, "") != args["original"]:
        raise ValueError("That card changed. Refresh before editing it.")
    if len(text) > CONTEXT_LIMITS[name]:
        raise ValueError(f"The {name} section holds at most {CONTEXT_LIMITS[name]:,} characters.")
    cards[name] = text
    note_id = f"context-{name}"
    stamp = stamp_now(ctx)
    existing = conn.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE notes SET text = ?, updated_on = ?, updated_at = ?
            WHERE id = ?
            """,
            (text, ctx_today(ctx).isoformat(), stamp, note_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO notes (
                id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
            ) VALUES (?, ?, ?, 'none', NULL, 0, NULL, NULL, NULL, ?)
            """,
            (note_id, name, text, stamp),
        )
    conn.commit()
    return {"context": cards}


def keep_note(args: dict, ctx: Any) -> dict:
    if args.get("context") in CONTEXT_LANES:
        return {"saved": save_context(args, ctx)}
    text = str(args.get("text") or "").strip()
    if not text or len(text) > 16000:
        raise ValueError("Write a note under 16,000 characters.")
    priority = args.get("priority")
    if priority not in (None, "high", "normal", "low"):
        raise ValueError("Unknown priority")
    conn = ctx_get(ctx, "conn")
    today = ctx_today(ctx)
    stamp = stamp_now(ctx)
    if args.get("kind") == "preference" or args.get("type") == "preference":
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        note_id = f"standing-{digest}"
        existing = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if existing:
            return {"saved": note_for_model(existing, today)}
        conn.execute(
            """
            INSERT INTO notes (
                id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
            ) VALUES (?, 'preference', ?, 'none', ?, 0, ?, NULL, NULL, ?)
            """,
            (note_id, text, priority, today.isoformat(), stamp),
        )
        conn.commit()
        return {"saved": note_for_model(conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone(), today)}
    label = _clean_kind(args.get("type"))
    leaving_open = bool(args.get("open"))
    if leaving_open and _open_count(conn) >= OPEN_NOTE_CAP:
        raise ValueError("Twenty-five notes are already pinned. Archive one before pinning another.")
    existing = conn.execute(
        "SELECT * FROM notes WHERE kind = ? AND text = ?",
        (label, text),
    ).fetchone()
    if existing:
        return {"saved": note_for_model(existing, today)}
    note_id = secrets.token_urlsafe(12)
    band = _clean_band(args.get("band")) if "band" in args else None
    color = _clean_color(args.get("color")) if "color" in args else "none"
    conn.execute(
        """
        INSERT INTO notes (
            id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            note_id,
            label,
            text,
            color,
            priority,
            1 if leaving_open else 0,
            today.isoformat(),
            band,
            stamp,
        ),
    )
    conn.commit()
    return {"saved": note_for_model(conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone(), today)}


def edit_note(args: dict, ctx: Any, *, delete: bool = False) -> dict:
    if args.get("context") in CONTEXT_LANES:
        if delete:
            raise ValueError("Context sections are cleared by editing them to empty text.")
        save_context(args, ctx)
        return {
            "status": "saved",
            "kind": args.get("context"),
            "message": "Notebook entry updated.",
        }
    kind = args.get("kind") or args.get("type")
    old_text = args["original"]
    if not isinstance(old_text, str) or (not delete and not isinstance(args.get("text"), str)):
        raise ValueError("Note text must be a string.")
    text = args.get("text", "").strip() if not delete else ""
    if not delete and (not text or len(text) > 16000):
        raise ValueError("Write a note under 16,000 characters.")
    conn = ctx_get(ctx, "conn")
    today = ctx_today(ctx)
    stamp = stamp_now(ctx)
    if kind == "preference":
        row = conn.execute(
            "SELECT * FROM notes WHERE kind = 'preference' AND text = ?",
            (old_text,),
        ).fetchone()
        if row is None:
            raise ValueError("This note changed. Refresh before editing it.")
        if delete:
            conn.execute("DELETE FROM notes WHERE id = ?", (row["id"],))
            conn.commit()
            return {
                "status": "deleted",
                "kind": "preference",
                "message": "Notebook entry deleted; chat history is unchanged.",
            }
        priority = row["priority"]
        if args.get("priority") in ("high", "normal", "low"):
            priority = args["priority"]
        # Preference ids are content-addressed on import; rewrite id when text changes.
        new_id = row["id"]
        if text != old_text:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            new_id = f"standing-{digest}"
            if new_id != row["id"] and conn.execute("SELECT 1 FROM notes WHERE id = ?", (new_id,)).fetchone():
                raise ValueError("This note changed. Refresh before editing it.")
            conn.execute("DELETE FROM notes WHERE id = ?", (row["id"],))
            conn.execute(
                """
                INSERT INTO notes (
                    id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
                ) VALUES (?, 'preference', ?, 'none', ?, ?, ?, ?, NULL, ?)
                """,
                (
                    new_id,
                    text,
                    priority,
                    row["open"],
                    row["written_on"] or today.isoformat(),
                    today.isoformat(),
                    stamp,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE notes SET text = ?, priority = ?, updated_on = ?, updated_at = ?
                WHERE id = ?
                """,
                (text, priority, today.isoformat(), stamp, row["id"]),
            )
        conn.commit()
        return {"status": "saved", "kind": "preference", "message": "Notebook entry updated."}
    if args.get("id"):
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (args["id"],)).fetchone()
        if row is None or row["text"] != old_text:
            raise ValueError("This note changed. Refresh before editing it.")
        if delete:
            conn.execute("DELETE FROM notes WHERE id = ?", (row["id"],))
            conn.commit()
            return {
                "status": "deleted",
                "kind": row["kind"],
                "message": "Notebook entry deleted; chat history is unchanged.",
            }
        new_kind = _clean_kind(args["type"]) if "type" in args else row["kind"]
        color = _clean_color(args["color"]) if "color" in args else row["color"]
        band = row["band"]
        if "band" in args:
            band = _clean_band(args["band"])
        was_open = bool(row["open"])
        open_note = was_open
        if "open" in args:
            opening = bool(args["open"])
            if opening and not was_open and _open_count(conn) >= OPEN_NOTE_CAP:
                raise ValueError("Twenty-five notes are already pinned. Archive one before pinning another.")
            open_note = opening
        priority = row["priority"]
        if args.get("priority") in ("high", "normal", "low"):
            priority = args["priority"]
        conn.execute(
            """
            UPDATE notes SET
                kind = ?, text = ?, color = ?, priority = ?, open = ?,
                updated_on = ?, band = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_kind,
                text,
                color,
                priority,
                1 if open_note else 0,
                today.isoformat(),
                band,
                stamp,
                row["id"],
            ),
        )
        if was_open and not open_note:
            title = " ".join(text.split())
            if len(title) > 80:
                title = title[:79] + "…"
            kitchen_log.record_event(
                conn,
                "note_archived",
                ref_id=row["id"],
                at=stamp,
                title=title,
                detail=new_kind,
                extra={"type": new_kind},
            )
        conn.commit()
        return {"status": "saved", "kind": new_kind, "message": "Notebook entry updated."}
    raise ValueError("Choose the note to change.")


def delete_note(args: dict, ctx: Any) -> dict:
    return edit_note(args, ctx, delete=True)


def search_notes(args: dict, ctx: Any) -> dict:
    query = str(args["query"]).strip().casefold()
    if not query or len(query) > 300:
        raise ValueError("Use a search phrase under 300 characters.")
    limit = min(30, max(1, int(args.get("limit", 12))))
    words = query.split()
    today = ctx_today(ctx)
    matches = [
        note
        for note in all_notes(ctx_get(ctx, "conn"), today)
        if all(word in note["text"].casefold() for word in words)
    ]
    matches.sort(key=lambda note: note.get("updated") or "", reverse=True)
    matches.sort(key=lambda note: {"high": 0, "normal": 1, "low": 2}[note["priority"]])
    return {
        "matches": matches[:limit],
        "limit_reached": len(matches) > limit,
        "searched_on": today.isoformat(),
    }


def analyze_notes(args: dict, ctx: Any) -> dict:
    today = ctx_today(ctx)
    conn = ctx_get(ctx, "conn")
    notes = all_notes(conn, today)
    pressing = [
        note
        for note in notes
        if note["open"] and note["type"] not in CONTEXT_LANES and note["type"] != "preference"
    ]
    pressing.sort(key=lambda note: note.get("updated") or "", reverse=True)
    pressing.sort(key=lambda note: {"high": 0, "normal": 1, "low": 2}[note["priority"]])
    recent = sorted(notes, key=lambda note: note.get("updated") or "", reverse=True)[:12]

    def clip(note):
        text = " ".join(note["text"].split())
        item = {key: value for key, value in note.items() if key != "text"}
        item["text"] = text[:360]
        if len(text) > 360:
            item["text_clipped"] = True
        return item

    return {
        "as_of": today.isoformat(),
        "counts": {
            "notes": len(notes),
            "open": len(pressing),
            "done": sum(note["done"] for note in notes),
            "high_open": sum(note["priority"] == "high" for note in pressing),
            "preferences": sum(note["type"] == "preference" for note in notes),
            "types": {
                label: sum(note["type"] == label for note in notes if note["type"] != "preference")
                for label in {note["type"] for note in notes if note["type"] != "preference"}
            },
        },
        "context": {name: _context_text(conn, name) for name in CONTEXT_LANES},
        "pressing": [clip(note) for note in pressing[:16]],
        "stale_open": [clip(note) for note in pressing if (note.get("days_since_update") or 0) >= 14][:8],
        "recent": [clip(note) for note in recent],
    }


def read_notes(args: dict, ctx: Any) -> dict:
    today = ctx_today(ctx)
    return {"as_of": today.isoformat(), "notes": all_notes(ctx_get(ctx, "conn"), today)}
