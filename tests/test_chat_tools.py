"""Each core tool against a small SQLite fixture. No network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from festin.chat.core_tools import build_core_registry
from festin.chat.messages import append_message, ensure_chat
from festin.schema import WEEKDAYS, connect

SAT = "2026-10-17"


class Ctx:
    def __init__(self, conn, data_dir, chat_id="chat-1"):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.chat_id = chat_id
        self.today = date(2026, 10, 18)


@pytest.fixture
def kit(blank_db, tmp_path):
    conn = connect(blank_db)
    data_dir = tmp_path / "data"
    (data_dir / "photos").mkdir(parents=True)
    ensure_chat(conn, "chat-1")
    # Seed one recipe.
    conn.execute(
        """
        INSERT INTO recipes (
            id, title, kind, voice, source, provenance, status, stub,
            cooks_before_log, ingredients_json, method, updated_at
        ) VALUES (?, ?, 'formule', 'zk', 'unknown', 'documented', 'draft', 0, 0, ?, '', ?)
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
        {"title": "Bread", "ingredients": ["flour"], "voice": "zk", "source": "unknown", "category": "breads", "searchDescription": "A plain loaf."},
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


def test_praxis_form_and_recipe_alias(kit):
    conn, registry, ctx = kit
    as_alias = registry.dispatch(
        "add_recipe",
        {
            "title": "Alias loaf",
            "kind": "recipe",
            "ingredients": ["flour"],
            "category": "breads",
            "searchDescription": "A loaf filed under the old kind name.",
        },
        ctx,
    )
    assert as_alias["recipe"]["kind"] == "formule"

    praxis = registry.dispatch(
        "add_recipe",
        {
            "title": "Phyllo",
            "kind": "praxis",
            "method": "Brush and layer.",
            "appliesTo": ["pastry", "spanakopita"],
            "category": "breads",
            "searchDescription": "Working with phyllo dough.",
        },
        ctx,
    )
    assert praxis["recipe"]["kind"] == "praxis"
    assert praxis["recipe"]["appliesTo"] == ["pastry", "spanakopita"]

    found = registry.dispatch("search_cookbook", {"kind": "praxis"}, ctx)
    assert any(r["id"] == praxis["id"] for r in found["results"])
    eggs = registry.dispatch(
        "add_recipe",
        {
            "title": "Fats",
            "kind": "praxis",
            "method": "Render slowly.",
            "appliesTo": ["eggs"],
            "category": "kitchen-craft",
            "searchDescription": "How a pan holds fat.",
        },
        ctx,
    )
    by_applies = registry.dispatch("search_cookbook", {"query": "eggs"}, ctx)
    assert any(r["id"] == eggs["id"] for r in by_applies["results"])
    assert all("egg" not in (r.get("title") or "").casefold() for r in by_applies["results"] if r["id"] == eggs["id"])
    aliased = registry.dispatch("search_cookbook", {"kind": "recipe"}, ctx)
    assert all(r["kind"] == "formule" for r in aliased["results"])
    assert any(r["id"] == as_alias["id"] for r in aliased["results"])


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

    # Household context is its own tool; keep_note stays a note.
    registry.dispatch(
        "update_household_context",
        {"section": "household", "text": "Three at the table."},
        ctx,
    )
    lane = conn.execute(
        "SELECT text FROM household_context WHERE section = 'household'"
    ).fetchone()
    assert "Three" in lane["text"]
    assert (
        conn.execute(
            "SELECT count(*) FROM notes WHERE id = 'context-household'"
        ).fetchone()[0]
        == 0
    )
    project = registry.dispatch(
        "keep_note",
        {"type": "project", "text": "UI refactor plan for the notes pane"},
        ctx,
    )
    assert project["saved"]["type"] == "project"
    assert "UI refactor" in project["saved"]["text"]

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
        "search_history", {"query": "pho winter"}, ctx
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


def test_search_history_finds_log_events(kit):
    conn, registry, ctx = kit
    from festin import log as kitchen_log

    kitchen_log.record_event(
        conn, "recipe_favourited", ref_id="CBK-0933", at="2026-10-19T01:55:00.000000Z",
        title="Venison Stroganoff", extra={"category": "meats"},
    )
    kitchen_log.record_event(
        conn, "note_archived", ref_id="note-elk", at="2026-10-19T02:15:00.000000Z",
        title="1.5 lbs elk stew meat", detail="note", extra={"type": "note"},
    )
    conn.commit()
    found = registry.dispatch("search_history", {"query": "stroganoff favourited"}, ctx)
    assert [e["id"] for e in found["log"]] == ["CBK-0933"]
    assert found["log"][0]["kind"] == "recipe_favourited"
    archived = registry.dispatch("search_history", {"query": "elk archived"}, ctx)
    assert [e["kind"] for e in archived["log"]] == ["note_archived"]


def test_search_history_lists_recent_days_without_words(kit):
    conn, registry, ctx = kit
    from unittest.mock import patch
    from datetime import date
    from festin import log as kitchen_log

    kitchen_log.record_event(conn, "recipe_cooked", ref_id="CBK-0001", at="2026-10-18T19:00:00.000000Z", title="Soup")
    kitchen_log.record_event(conn, "recipe_added", ref_id="CBK-0002", at="2026-08-01T19:00:00.000000Z", title="Old")
    conn.commit()
    with patch("festin.log.household_today", return_value=date(2026, 10, 19)):
        recent = registry.dispatch("search_history", {"days": 7}, ctx)
    assert [e["id"] for e in recent["log"]] == ["CBK-0001"]
    assert recent["matches"] == []
    with pytest.raises(ValueError):
        registry.dispatch("search_history", {}, ctx)


def test_kept_note_starts_pinned_unless_asked_closed(kit):
    conn, registry, ctx = kit
    pinned = registry.dispatch("keep_note", {"text": "Buy lemons", "type": "shopping"}, ctx)
    assert pinned["saved"]["open"] is True
    closed = registry.dispatch("keep_note", {"text": "Old idea", "type": "note", "open": False}, ctx)
    assert closed["saved"]["open"] is False


def test_analyze_cookbook_favourites_and_queue_follow_scope(kit):
    conn, registry, ctx = kit
    from festin import log as kitchen_log

    def plant(recipe_id, title, category, *, favourite=0, queued_at=None, cooks_before_log=0):
        conn.execute(
            """
            INSERT INTO recipes (
                id, title, category, favourite, queued_at, cooks_before_log
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (recipe_id, title, category, favourite, queued_at, cooks_before_log),
        )

    plant("CBK-0101", "Never Stew", "soups-stews", favourite=1, cooks_before_log=2)
    plant("CBK-0102", "Older Stew", "soups-stews", favourite=1)
    plant("CBK-0103", "Recent Stew", "soups-stews", favourite=1)
    plant("CBK-0104", "Early Queue", "soups-stews", queued_at="2026-01-02T12:00:00.000Z")
    plant("CBK-0105", "Late Queue", "soups-stews", queued_at="2026-08-01T12:00:00.000Z")
    plant("CBK-0106", "Bread Heart", "breads", favourite=1)
    plant("CBK-0107", "Bread Queue", "breads", queued_at="2026-03-01T12:00:00.000Z")
    kitchen_log.record_event(
        conn, "recipe_cooked", ref_id="CBK-0102", at="2020-01-01T18:00:00.000Z",
        title="Older Stew", extra={"date": "2020-01-01"},
    )
    kitchen_log.record_event(
        conn, "recipe_cooked", ref_id="CBK-0103", at="2026-06-01T18:00:00.000Z",
        title="Recent Stew", extra={"date": "2026-06-01"},
    )
    conn.commit()

    report = registry.dispatch("analyze_cookbook", {}, ctx)
    hearts = report["favourites"]
    queue = report["to_cook"]
    assert [row["id"] for row in hearts] == ["CBK-0101", "CBK-0106", "CBK-0102", "CBK-0103"]
    assert hearts[0]["lastCooked"] is None
    assert hearts[0]["cookCount"] == 2
    assert hearts[2]["lastCooked"] == "2020-01-01"
    assert hearts[2]["cookCount"] == 1
    assert [row["id"] for row in queue] == ["CBK-0104", "CBK-0107", "CBK-0105"]
    assert set(hearts[0]) == {"id", "title", "category", "cookCount", "lastCooked"}
    assert set(queue[0]) == {"id", "title", "category", "queuedAt", "cookCount"}
    assert hearts[0]["title"] == "Never Stew"
    assert queue[0]["queuedAt"] == "2026-01-02T12:00:00.000Z"

    scoped = registry.dispatch("analyze_cookbook", {"category": "soups-stews"}, ctx)
    assert [row["id"] for row in scoped["favourites"]] == ["CBK-0101", "CBK-0102", "CBK-0103"]
    assert [row["id"] for row in scoped["to_cook"]] == ["CBK-0104", "CBK-0105"]
    assert all(row["category"] == "soups-stews" for row in scoped["favourites"] + scoped["to_cook"])


def test_new_chat_omits_the_queue(blank_db, tmp_path):
    from festin.chat.messages import build_chat_messages
    from festin.settings import get_settings

    conn = connect(blank_db)
    conn.execute(
        """
        INSERT INTO recipes (id, title, category, queued_at)
        VALUES (?, ?, ?, ?)
        """,
        ("CBK-0201", "Queued stew", "soups-stews", "2026-10-01T12:00:00.000Z"),
    )
    conn.commit()
    messages, _stored = build_chat_messages(
        conn,
        chat_id="chat-new",
        settings=get_settings(conn),
        week="2026-10-17",
        editor_plan=None,
        image_support=False,
        data_dir=tmp_path,
        opening_extras={"plugin_context": ["tattva: earth"]},
    )
    opening = next(
        message["content"]
        for message in messages
        if str(message["content"]).startswith("New-chat context:")
    )
    payload = json.loads(opening.split("\n", 1)[1])
    assert "to_cook" not in payload
    assert set(payload["household_context"]) == {"household", "preferences", "restrictions"}
    assert payload["current_week_dinners"]["days"]
    assert payload["selected_dinner_week"] == "2026-10-17"
    assert payload["five_day_weather"].startswith("Weather:")
    assert payload["plugin_context"] == ["tattva: earth"]
    assert payload["model_accepts_images"] is False
    conn.close()


def test_babette_new_recipe_is_generated(kit):
    conn, registry, ctx = kit
    saved = registry.dispatch(
        "add_recipe",
        {"title": "Herb toast", "ingredients": ["bread", "herbs"], "method": "Toast.", "category": "snacks-sandwiches", "searchDescription": "Toast with herbs."},
        ctx,
    )
    assert saved["recipe"]["provenance"] == "generated"
    with pytest.raises(ValueError, match="category"):
        registry.dispatch("add_recipe", {"title": "Bare", "ingredients": ["x"], "searchDescription": "A bare thing."}, ctx)
    with pytest.raises(ValueError, match="searchDescription"):
        registry.dispatch("add_recipe", {"title": "Bare", "ingredients": ["x"], "category": "misc"}, ctx)
