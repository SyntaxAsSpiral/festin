"""Household context sections: standing facts, separate from notes."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from festin.errors import StaleState

CONTEXT_LANES = ("household", "preferences", "restrictions")
CONTEXT_LIMITS = {"household": 800, "preferences": 800, "restrictions": 1000}
SECTIONS = CONTEXT_LANES


def _ctx_get(ctx: Any, key: str, default=None):
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def get_section(conn: sqlite3.Connection, section: str) -> dict:
    name = _clean_section(section)
    row = conn.execute(
        "SELECT section, text, updated_at FROM household_context WHERE section = ?",
        (name,),
    ).fetchone()
    if row is None:
        return {"section": name, "text": "", "updatedAt": None}
    return {"section": row["section"], "text": row["text"] or "", "updatedAt": row["updated_at"]}


def all_sections(conn: sqlite3.Connection) -> dict[str, str]:
    out = {name: "" for name in SECTIONS}
    for row in conn.execute("SELECT section, text FROM household_context").fetchall():
        if row["section"] in out:
            out[row["section"]] = row["text"] or ""
    return out


def put_section(
    conn: sqlite3.Connection,
    section: str,
    body: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Replace one section from Settings. Conflict when expected_updated_at mismatches."""
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    name = _clean_section(section)
    text = str(body.get("text") or "").strip()
    if not text:
        raise ValueError("Write a short note before saving.")
    if len(text) > CONTEXT_LIMITS[name]:
        raise ValueError(f"The {name} section holds at most {CONTEXT_LIMITS[name]:,} characters.")
    current = get_section(conn, name)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != current["updatedAt"]:
        raise StaleState("This section changed. Refresh before editing it.")
    stamp = _stamp(now)
    conn.execute(
        """
        INSERT INTO household_context (section, text, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(section) DO UPDATE SET text = excluded.text, updated_at = excluded.updated_at
        """,
        (name, text, stamp),
    )
    conn.commit()
    return get_section(conn, name)


def update_household_context(args: dict, ctx: Any) -> dict:
    """Core tool: append a line by default; replace only with the version stamp."""
    name = _clean_section(args.get("section"))
    text = str(args.get("text") or "").strip()
    if not text and args.get("mode", "append") != "replace":
        raise ValueError("Write the line to add.")
    mode = str(args.get("mode") or "append").strip().casefold()
    if mode not in ("append", "replace"):
        raise ValueError("mode is append or replace.")
    conn = _ctx_get(ctx, "conn")
    current = get_section(conn, name)
    if mode == "append":
        existing = current["text"]
        if text and text.casefold() not in existing.casefold():
            combined = (existing + ("\n" if existing else "") + text).strip()
        else:
            combined = existing
    else:
        if "expected_updated_at" not in args:
            raise ValueError("replace needs expected_updated_at from the current section.")
        expected = args.get("expected_updated_at")
        if expected != current["updatedAt"]:
            raise ValueError("That section changed. Refresh before editing it.")
        combined = text
    if len(combined) > CONTEXT_LIMITS[name]:
        raise ValueError(f"The {name} section holds at most {CONTEXT_LIMITS[name]:,} characters.")
    now = _ctx_get(ctx, "now")
    stamp = _stamp(now if isinstance(now, datetime) else None)
    conn.execute(
        """
        INSERT INTO household_context (section, text, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(section) DO UPDATE SET text = excluded.text, updated_at = excluded.updated_at
        """,
        (name, combined, stamp),
    )
    conn.commit()
    return {"saved": get_section(conn, name), "sections": all_sections(conn)}


def _clean_section(value) -> str:
    name = str(value or "").strip().casefold()
    if name not in SECTIONS:
        raise ValueError("Choose household, preferences, or restrictions.")
    return name


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
