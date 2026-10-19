"""Each core tool against a small SQLite fixture. No network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from festin.chat.core_tools import build_core_registry
from festin.chat.messages import append_message, ensure_chat
from festin.schema import WEEKDAYS, apply, connect

SAT = "2026-10-17"


class Ctx:
    def __init__(self, conn, data_dir, chat_id="chat-1"):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.chat_id = chat_id
        self.today = date(2026, 10, 18)


@pytest.fixture
def kit(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    apply(conn)
    data_dir = tmp_path / "data"
    (data_dir / "photos").mkdir(parents=True)
    ensure_chat(conn, "chat-1")
    # Seed one recipe.
    conn.execute(
        """
        INSERT INTO recipes (
            id, title, kind, voice, source, provenance, status, stub,
            needs_practice_review, ingredients_json, method, updated_at
        ) VALUES (?, ?, 'recipe', 'zk', 'unknown', 'documented', 'draft', 0, 0, ?, '', ?)
        """,
        ("CBK-0001", "Soup", json.dumps(["water", "salt"]), "2026-01-01T00:00:00+00:00"),
    )
    conn.execute("UPDATE catalog_meta SET next_numeric_id = 2 WHERE id = 1")
    conn.commit()
    registry = build_core_registry()
    ctx = Ctx(conn, data_dir)
    yield conn, registry, ctx
    conn.close()


def test_recipe_tools(kit):
    conn, registry, ctx = kit
    added = registry.dispatch(
        "add_recipe",
        {"title": "Bread", "ingredients": ["flour"], "voice": "zk", "source": "unknown"},
        ctx,
    )
    assert added["status"] == "saved"
    assert added["id"].startswith("CBK-")

    found = registry.dispatch("search_cookbook", {"query": "Soup"}, ctx)
    assert found["total"] >= 1
    assert any(r["id"] == "CBK-0001" for r in found["results"])

    edited = registry.dispatch(
        "edit_recipe",
        {
            "recipe_id": "CBK-0001",
            "expected_updated_at": "2026-01-01T00:00:00+00:00",
            "changes": {"notes": "salt to taste"},
        },
        ctx,
    )
    assert edited["status"] == "saved"
    stamp = edited["recipe"]["updatedAt"]

    with pytest.raises(ValueError, match="Recipe changed"):
        registry.dispatch(
            "edit_recipe",
            {
                "recipe_id": "CBK-0001",
                "expected_updated_at": "2026-01-01T00:00:00+00:00",
                "changes": {"notes": "stale"},
            },
            ctx,
        )

    appended = registry.dispatch(
        "append_recipe_context",
        {"recipe_id": "CBK-0001", "expected_updated_at": stamp, "text": "Served hot."},
        ctx,
    )
    assert "Served hot." in appended["recipe"]["context"]
    stamp = appended["recipe"]["updatedAt"]

    analyzed = registry.dispatch("analyze_cookbook", {}, ctx)
    assert analyzed["count"] >= 2

    deleted = registry.dispatch(
        "delete_recipe",
        {"recipe_id": added["id"], "expected_updated_at": added["recipe"]["updatedAt"]},
        ctx,
    )
    assert deleted["status"] == "deleted"


def test_edit_recipe_favourite_and_search(kit):
    conn, registry, ctx = kit
    loved = registry.dispatch(
        "edit_recipe",
        {
            "recipe_id": "CBK-0001",
            "expected_updated_at": "2026-01-01T00:00:00+00:00",
            "changes": {"favourite": True},
        },
        ctx,
    )
    assert loved["status"] == "saved"
    assert loved["recipe"]["favourite"] is True

    found = registry.dispatch("search_cookbook", {"query": "Soup", "favourite": True}, ctx)
    assert found["total"] == 1
    assert found["results"][0]["id"] == "CBK-0001"
    assert found["results"][0]["favourite"] is True

    empty = registry.dispatch("search_cookbook", {"query": "Soup", "favourite": False}, ctx)
    assert empty["total"] == 0

    full = registry.dispatch(
        "search_cookbook",
        {"query": "Soup", "favourite": True, "full": True},
        ctx,
    )
    assert full["results"][0]["favourite"] is True


def test_attach_recipe_photos(kit):
    conn, registry, ctx = kit
    photo = ctx.data_dir / "photos" / "dish.jpg"
    photo.write_bytes(b"not-a-real-jpeg-but-file-exists")
    append_message(
        conn,
        "chat-1",
        {"role": "user", "content": "look", "photos": ["/photos/dish.jpg"]},
    )
    result = registry.dispatch(
        "attach_recipe_photos",
        {
            "recipe_id": "CBK-0001",
            "expected_updated_at": "2026-01-01T00:00:00+00:00",
            "photo_paths": ["/photos/dish.jpg"],
        },
        ctx,
    )
    assert result["status"] == "saved"
    assert any("dish.jpg" in p for p in result["photos"])


def test_note_tools(kit):
    conn, registry, ctx = kit
    kept = registry.dispatch(
        "keep_note",
        {"type": "shopping", "text": "cream", "color": "green", "open": True},
        ctx,
    )
    assert kept["saved"]["text"] == "cream"
    note_id = kept["saved"]["id"]

    searched = registry.dispatch("search_notes", {"query": "cream"}, ctx)
    assert searched["matches"]

    analyzed = registry.dispatch("analyze_notes", {}, ctx)
    assert analyzed["counts"]["open"] >= 1

    all_of = registry.dispatch("read_notes", {}, ctx)
    assert any(n.get("text") == "cream" for n in all_of["notes"])

    registry.dispatch(
        "edit_note",
        {"id": note_id, "original": "cream", "text": "heavy cream", "color": "sky"},
        ctx,
    )
    row = conn.execute("SELECT text, color FROM notes WHERE id = ?", (note_id,)).fetchone()
    assert row["text"] == "heavy cream"

    # Context lane.
    registry.dispatch(
        "keep_note",
        {"context": "household", "text": "Three at the table."},
        ctx,
    )
    lane = conn.execute(
        "SELECT text FROM notes WHERE id = 'context-household'"
    ).fetchone()
    assert "Three" in lane["text"]

    registry.dispatch(
        "delete_note", {"id": note_id, "original": "heavy cream"}, ctx
    )
    assert conn.execute("SELECT count(*) FROM notes WHERE id = ?", (note_id,)).fetchone()[0] == 0


def test_propose_dinners(kit):
    conn, registry, ctx = kit
    days = [
        {"day": d, "recipe": None, "title": "Soup" if d == "sun" else "", "ingredients": []}
        for d in WEEKDAYS
    ]
    # Unique title links to CBK-0001.
    days[1]["title"] = "Soup"
    result = registry.dispatch(
        "propose_dinners",
        {"weekStart": SAT, "days": days, "expected_updated_at": None},
        ctx,
    )
    assert result["saved"] is True
    night = conn.execute(
        "SELECT recipe_id, title FROM nights WHERE date = '2026-10-18'"
    ).fetchone()
    assert night["recipe_id"] == "CBK-0001"
    assert night["title"] == "Soup"

    stamp = result["proposed"]["updatedAt"]
    with pytest.raises(ValueError, match="already has saved dinners"):
        registry.dispatch(
            "propose_dinners",
            {"weekStart": SAT, "days": days, "expected_updated_at": None},
            ctx,
        )
    # Correct stamp replaces.
    days[1]["title"] = "Soup again"
    again = registry.dispatch(
        "propose_dinners",
        {"weekStart": SAT, "days": days, "expected_updated_at": stamp},
        ctx,
    )
    assert again["saved"] is True


def test_chat_history_tools(kit):
    conn, registry, ctx = kit
    ensure_chat(conn, "old-chat", title="Old talk")
    append_message(conn, "old-chat", {"role": "user", "content": "We made pho last winter"})
    append_message(conn, "old-chat", {"role": "assistant", "content": "Oui, the broth."})
    found = registry.dispatch(
        "search_chat_history", {"query": "pho winter"}, ctx
    )
    assert found["matches"]
    assert found["matches"][0]["chat_id"] == "old-chat"
    read = registry.dispatch(
        "read_chat_history",
        {"chat_id": "old-chat", "start": 0, "limit": 10},
        ctx,
    )
    assert read["total_messages"] == 2
    assert "pho" in read["messages"][0]["content"]
