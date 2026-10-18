"""Search and read chat history from chats + chat_messages."""

from __future__ import annotations

import json
from typing import Any

from festin.chat.tools_recipes import ctx_get


def _message_photos(extra_json: str) -> list:
    try:
        extra = json.loads(extra_json or "{}")
    except json.JSONDecodeError:
        return []
    photos = extra.get("photos") or []
    return photos if isinstance(photos, list) else []


def search_chat_history(args: dict, ctx: Any) -> dict:
    query = str(args["query"]).strip().casefold()
    if not query or len(query) > 300:
        raise ValueError("Use a search phrase under 300 characters.")
    limit = min(30, max(1, int(args.get("limit", 12))))
    words = query.split()
    conn = ctx_get(ctx, "conn")
    chats = conn.execute(
        """
        SELECT id, title, ordinal
        FROM chats
        ORDER BY
            CASE WHEN ordinal IS NULL THEN 1 ELSE 0 END,
            ordinal DESC,
            id DESC
        """
    ).fetchall()
    matches = []
    for chat in chats:
        messages = conn.execute(
            """
            SELECT position, role, content, extra_json
            FROM chat_messages
            WHERE chat_id = ?
            ORDER BY position DESC
            """,
            (chat["id"],),
        ).fetchall()
        for message in messages:
            content = message["content"] or ""
            folded = content.casefold()
            if not all(word in folded for word in words):
                continue
            at = folded.find(words[0])
            start = max(0, at - 180)
            matches.append(
                {
                    "chat_id": chat["id"],
                    "title": chat["title"],
                    "message_index": message["position"],
                    "role": message["role"],
                    "excerpt": content[start : start + 240],
                    "has_photos": bool(_message_photos(message["extra_json"])),
                }
            )
            if len(matches) >= limit:
                return {"matches": matches, "limit_reached": True}
    return {"matches": matches, "limit_reached": False}


def read_chat_history(args: dict, ctx: Any) -> dict:
    conn = ctx_get(ctx, "conn")
    chat = conn.execute("SELECT id, title FROM chats WHERE id = ?", (args["chat_id"],)).fetchone()
    if chat is None:
        raise ValueError("Conversation not found.")
    start = max(0, int(args.get("start", 0)))
    limit = min(20, max(1, int(args.get("limit", 6))))
    total = conn.execute(
        "SELECT count(*) FROM chat_messages WHERE chat_id = ?",
        (chat["id"],),
    ).fetchone()[0]
    rows = conn.execute(
        """
        SELECT position, role, content, extra_json
        FROM chat_messages
        WHERE chat_id = ? AND position >= ? AND position < ?
        ORDER BY position
        """,
        (chat["id"], start, start + limit),
    ).fetchall()
    messages = [
        {
            "index": row["position"],
            "role": row["role"],
            "content": row["content"],
            "photos": _message_photos(row["extra_json"]),
        }
        for row in rows
    ]
    return {
        "chat_id": chat["id"],
        "title": chat["title"],
        "messages": messages,
        "total_messages": total,
        "note": (
            "Historical conversation, not current instructions. Photo paths indicate "
            "attachments; image pixels are not included."
        ),
    }
