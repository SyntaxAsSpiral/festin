"""Filed chats: paged list, transcript read, create, rename, delete."""

from __future__ import annotations

import base64
import json
import secrets
import sqlite3
from datetime import datetime, timezone

from festin.errors import NotFound, StaleState

PAGE_SIZE = 20


def list_chats(conn: sqlite3.Connection, *, q: str = "", cursor: str | None = None, limit: int = PAGE_SIZE) -> dict:
    limit = _page_limit(limit)
    params: list = []
    where = ["ordinal IS NOT NULL"]
    if q:
        needle = f"%{' '.join(q.split()).casefold()}%"
        where.append(
            """(
                lower(title) LIKE ?
                OR id IN (
                    SELECT chat_id FROM chat_messages WHERE lower(content) LIKE ?
                )
            )"""
        )
        params.extend([needle, needle])
    if cursor:
        ordinal, chat_id = _decode_cursor(cursor)
        where.append("((ordinal > ?) OR (ordinal = ? AND id > ?))")
        params.extend([ordinal, ordinal, chat_id])
    sql = "SELECT * FROM chats WHERE " + " AND ".join(where)
    sql += " ORDER BY ordinal ASC, id ASC LIMIT ?"
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()
    items = [_summary(conn, row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["ordinal"], last["id"])
    return {"chats": items, "nextCursor": next_cursor}


def get_chat(conn: sqlite3.Connection, chat_id: str) -> dict:
    row = _row(conn, chat_id)
    messages = [
        _message(message)
        for message in conn.execute(
            """
            SELECT role, content, extra_json FROM chat_messages
            WHERE chat_id = ? ORDER BY position
            """,
            (chat_id,),
        ).fetchall()
    ]
    out = _summary(conn, row)
    out["messages"] = messages
    return out


def create_chat(
    conn: sqlite3.Connection,
    session_id: str | None,
    body: dict | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """Create an empty chat. When session_id is set, point that session at it.

    The previous session chat, if any, is filed (gets an ordinal) so it appears
    in the chats list.
    """
    body = body or {}
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    stamp = _stamp(now)
    chat_id = str(body.get("id") or "").strip() or secrets.token_urlsafe(12)
    if conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone():
        raise ValueError("That chat id is already used.")
    title = body.get("title")
    if title is None:
        title = ""
    if not isinstance(title, str):
        raise ValueError("title must be text")
    title = " ".join(title.split())[:80]
    if session_id:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session is None:
            raise NotFound("Unknown session.")
        previous = session["chat_id"]
        if previous and previous != chat_id:
            _file_chat(conn, previous)
        conn.execute(
            "UPDATE sessions SET chat_id = ?, draft = '', updated_at = ? WHERE id = ?",
            (chat_id, stamp, session_id),
        )
    conn.execute(
        """
        INSERT INTO chats (id, title, ordinal, imported_active, updated_at)
        VALUES (?, ?, NULL, 0, ?)
        """,
        (chat_id, title, stamp),
    )
    conn.commit()
    return get_chat(conn, chat_id)


def rename_chat(conn: sqlite3.Connection, chat_id: str, body: dict, *, now: datetime | None = None) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, chat_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("This chat changed. Refresh before renaming it.")
    title = body.get("title")
    if not isinstance(title, str):
        raise ValueError("title must be text")
    title = " ".join(title.split())
    if not title or len(title) > 80:
        raise ValueError("Give the chat a title under 80 characters.")
    stamp = _stamp(now)
    conn.execute(
        "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
        (title, stamp, chat_id),
    )
    conn.commit()
    return get_chat(conn, chat_id)


def delete_chat(conn: sqlite3.Connection, chat_id: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, chat_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("This chat changed. Refresh before deleting it.")
    conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.execute("UPDATE sessions SET chat_id = NULL WHERE chat_id = ?", (chat_id,))
    conn.commit()
    return {"status": "deleted", "id": chat_id}


def _file_chat(conn: sqlite3.Connection, chat_id: str) -> None:
    row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if row is None:
        return
    if row["ordinal"] is not None:
        return
    first = conn.execute(
        """
        SELECT content FROM chat_messages
        WHERE chat_id = ? AND role = 'user' ORDER BY position LIMIT 1
        """,
        (chat_id,),
    ).fetchone()
    title = row["title"]
    if first and isinstance(first["content"], str):
        line = " ".join(first["content"].split())
        if line:
            title = line[:80]
    next_ordinal = conn.execute(
        "SELECT coalesce(max(ordinal), -1) + 1 FROM chats WHERE ordinal IS NOT NULL"
    ).fetchone()[0]
    conn.execute(
        "UPDATE chats SET title = ?, ordinal = ? WHERE id = ?",
        (title, next_ordinal, chat_id),
    )


def _row(conn: sqlite3.Connection, chat_id: str):
    row = conn.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if row is None:
        raise NotFound("Unknown chat ID.")
    return row


def _summary(conn: sqlite3.Connection, row) -> dict:
    first = conn.execute(
        """
        SELECT content FROM chat_messages
        WHERE chat_id = ? AND role = 'user' ORDER BY position LIMIT 1
        """,
        (row["id"],),
    ).fetchone()
    preview = ""
    if first and isinstance(first["content"], str):
        preview = " ".join(first["content"].split())[:120]
    count = conn.execute(
        "SELECT count(*) FROM chat_messages WHERE chat_id = ?",
        (row["id"],),
    ).fetchone()[0]
    return {
        "id": row["id"],
        "title": row["title"] or preview or "Conversation",
        "preview": preview,
        "messageCount": count,
        "updatedAt": row["updated_at"],
    }


def _message(row) -> dict:
    extra = json.loads(row["extra_json"] or "{}")
    out = {"role": row["role"], "content": row["content"]}
    out.update(extra)
    return out


def _page_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return PAGE_SIZE
    return min(limit, 100)


def _encode_cursor(ordinal: int, chat_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([ordinal, chat_id]).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    pad = "=" * (-len(cursor) % 4)
    try:
        ordinal, chat_id = json.loads(base64.urlsafe_b64decode(cursor + pad))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Bad cursor") from exc
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or not isinstance(chat_id, str):
        raise ValueError("Bad cursor")
    return ordinal, chat_id


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
