"""To-cook queue and the plain Cooked action (festin-3d6.45)."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone

import pytest

from festin import plans as plans_mod
from festin import recipes as recipes_mod
from festin.schema import SCHEMA_VERSION, apply, connect
from festin.settings import get_settings, today, week_start_for
from tests.conftest import reset_db_file, start_kitchen, stop_kitchen
from tests.test_api import Client


@pytest.fixture(scope="module")
def _queue_server(migrated_template, tmp_path_factory):
    root = tmp_path_factory.mktemp("queue")
    db = root / "store.sqlite"
    photos = root / "cooking-photos"
    shutil.copy2(migrated_template, db)
    server = start_kitchen(db, photos_dir=photos)
    try:
        yield server, db, migrated_template
    finally:
        stop_kitchen(server)


@pytest.fixture
def kitchen(_queue_server):
    server, db, template = _queue_server
    reset_db_file(db, template)
    yield server


def test_v14_database_gains_queued_at_and_planned_at_v15(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    from festin.schema import MIGRATIONS

    for step in MIGRATIONS[:14]:
        step(conn)
    conn.execute("PRAGMA user_version = 14")
    conn.execute(
        """
        INSERT INTO recipes (
            id, title, kind, category, voice, source, provenance, status, stub,
            needs_practice_review, favourite, search_description, method, notes,
            context, ocr_text, ingredients_json, applies_to_json, tattva_json,
            photos_json, created_at, updated_at, extra_json
        ) VALUES (
            'CBK-0001', 'Soup', 'formule', 'soups-stews', '', '', 'documented', 'draft', 0,
            0, 0, '', '', '', '', '', '[]', '[]', '[]', '[]', NULL, NULL, '{}'
        )
        """
    )
    conn.commit()
    assert "queued_at" not in {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "queued_at" in {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
    kinds = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'kitchen_log_events'"
    ).fetchone()[0]
    assert "recipe_planned" in kinds
    row = conn.execute("SELECT queued_at FROM recipes WHERE id = 'CBK-0001'").fetchone()
    assert row["queued_at"] is None
    conn.close()


def test_queue_toggle_filter_order_and_log(kitchen):
    client = Client(kitchen.server_address[1])
    status, first = client.request(
        "POST",
        "/api/recipes",
        {"title": "Alpha Stew", "ingredients": ["beans"], "category": "soups-stews"},
    )
    assert status == 201
    assert first.get("queuedAt") is None

    status, second = client.request(
        "POST",
        "/api/recipes",
        {"title": "Beta Pie", "ingredients": ["flour"], "category": "pies-tarts"},
    )
    assert status == 201

    status, queued_first = client.request(
        "POST",
        f"/api/recipes/{first['id']}",
        {"expected_updated_at": first["updatedAt"], "queued": True},
    )
    assert status == 200
    assert queued_first["queuedAt"]

    status, queued_second = client.request(
        "POST",
        f"/api/recipes/{second['id']}",
        {"expected_updated_at": second["updatedAt"], "queued": True},
    )
    assert status == 200
    assert queued_second["queuedAt"] > queued_first["queuedAt"]

    status, page = client.request("GET", "/api/recipes?queued=1")
    assert status == 200
    ids = [r["id"] for r in page["recipes"]]
    assert ids[:2] == [first["id"], second["id"]]

    status, cleared = client.request(
        "POST",
        f"/api/recipes/{first['id']}",
        {"expected_updated_at": queued_first["updatedAt"], "queued": False},
    )
    assert status == 200
    assert cleared["queuedAt"] is None

    status, body = client.request("GET", "/api/log")
    assert status == 200
    planned = [
        e
        for e in body["entries"]
        if e.get("kind") == "recipe_planned" and e.get("id") in (first["id"], second["id"])
    ]
    assert {e["id"] for e in planned} == {first["id"], second["id"]}


def test_sample_puts_queued_first(blank_db):
    conn = connect(blank_db)
    early = recipes_mod.create_recipe(
        conn,
        {"title": "Queued early", "ingredients": ["a"], "category": "casseroles", "queued": True},
        now=datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
    )
    late = recipes_mod.create_recipe(
        conn,
        {"title": "Queued late", "ingredients": ["b"], "category": "casseroles", "queued": True},
        now=datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc),
    )
    for i in range(20):
        recipes_mod.create_recipe(
            conn, {"title": f"Random {i:02d}", "ingredients": ["x"], "category": "casseroles"}
        )
    page = recipes_mod.list_recipes(conn, limit=5, sample=True, categories=["casseroles"])
    ids = [r["id"] for r in page["recipes"]]
    assert ids[0] == early["id"]
    assert ids[1] == late["id"]
    conn.close()


def test_cooked_clears_queue_and_review_without_slip_overwrite(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {
            "title": "Missed Roast",
            "ingredients": ["beef"],
            "category": "meats",
            "needsPracticeReview": True,
            "queued": True,
        },
    )
    assert status == 201
    assert recipe["needsPracticeReview"] is True
    assert recipe["queuedAt"]

    conn = connect(kitchen.db_path)
    start = week_start_for(today(conn), get_settings(conn)["week_start_day"]).isoformat()
    before = plans_mod.get_plan(conn, start)
    conn.close()

    status, cooked = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/cooked",
        {"expected_updated_at": recipe["updatedAt"]},
    )
    assert status == 200
    assert cooked["needsPracticeReview"] is False
    assert cooked["queuedAt"] is None

    conn = connect(kitchen.db_path)
    after = plans_mod.get_plan(conn, start)
    conn.close()
    assert after["days"] == before["days"]

    status, body = client.request("GET", "/api/log")
    cooks = [
        e for e in body["entries"] if e.get("kind") == "recipe_cooked" and e.get("id") == recipe["id"]
    ]
    assert len(cooks) == 1
    assert cooks[0]["detail"]  # cook date carried on the event


def test_cooked_marks_matching_uncooked_night(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Slip Soup", "ingredients": ["stock"], "category": "soups-stews", "queued": True},
    )
    assert status == 201

    conn = connect(kitchen.db_path)
    day = today(conn)
    start = week_start_for(day, get_settings(conn)["week_start_day"])
    plan = plans_mod.get_plan(conn, start.isoformat())
    days = []
    for slot in plan["days"]:
        if slot["date"] == day.isoformat():
            days.append(
                {
                    **slot,
                    "recipe": recipe["id"],
                    "title": recipe["title"],
                    "cooked": False,
                }
            )
        else:
            days.append(dict(slot))
    plans_mod.save_plan(
        conn,
        start.isoformat(),
        {
            "weekStart": start.isoformat(),
            "expected_updated_at": plan["updatedAt"],
            "days": days,
            "slipTitle": plan.get("slipTitle") or "",
            "notes": plan.get("notes") or "",
        },
    )
    # Re-read after plan save (may have cleared queue already? No — night was uncooked).
    fresh = recipes_mod.get_recipe(conn, recipe["id"])
    conn.close()
    assert fresh["queuedAt"]  # still queued until /cooked or a cooked night

    status, cooked = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/cooked",
        {"expected_updated_at": fresh["updatedAt"]},
    )
    assert status == 200
    assert cooked["queuedAt"] is None

    conn = connect(kitchen.db_path)
    night = conn.execute(
        "SELECT cooked, recipe_id FROM nights WHERE date = ?", (day.isoformat(),)
    ).fetchone()
    assert night["recipe_id"] == recipe["id"]
    assert night["cooked"] == 1
    conn.close()


def test_slip_toggle_clears_queue_and_review(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {
            "title": "Slip Clear",
            "ingredients": ["onion"],
            "category": "soups-stews",
            "needsPracticeReview": True,
            "queued": True,
        },
    )
    assert status == 201

    conn = connect(kitchen.db_path)
    day = today(conn)
    start = week_start_for(day, get_settings(conn)["week_start_day"])
    plan = plans_mod.get_plan(conn, start.isoformat())
    days = []
    for slot in plan["days"]:
        if slot["date"] == day.isoformat():
            days.append(
                {
                    **slot,
                    "recipe": recipe["id"],
                    "title": recipe["title"],
                    "cooked": True,
                }
            )
        else:
            days.append(dict(slot))
    plans_mod.save_plan(
        conn,
        start.isoformat(),
        {
            "weekStart": start.isoformat(),
            "expected_updated_at": plan["updatedAt"],
            "days": days,
            "slipTitle": "",
            "notes": "",
        },
    )
    saved = recipes_mod.get_recipe(conn, recipe["id"])
    conn.close()
    assert saved["queuedAt"] is None
    assert saved["needsPracticeReview"] is False


def test_babette_queue_via_edit_recipe(blank_db, tmp_path):
    from datetime import date
    from pathlib import Path

    from festin.chat.core_tools import build_core_registry
    from festin.chat.messages import ensure_chat

    class Ctx:
        def __init__(self, conn, data_dir):
            self.conn = conn
            self.data_dir = Path(data_dir)
            self.chat_id = "chat-1"
            self.today = date(2026, 10, 18)

    conn = connect(blank_db)
    data_dir = tmp_path / "data"
    (data_dir / "photos").mkdir(parents=True)
    ensure_chat(conn, "chat-1")
    registry = build_core_registry()
    ctx = Ctx(conn, data_dir)
    added = registry.dispatch(
        "add_recipe",
        {
            "title": "Queued by Babette",
            "ingredients": ["lentils"],
            "category": "soups-stews",
            "searchDescription": "A pot of lentils.",
        },
        ctx,
    )
    recipe = added["recipe"]
    queued = registry.dispatch(
        "edit_recipe",
        {
            "recipe_id": recipe["id"],
            "expected_updated_at": recipe["updatedAt"],
            "changes": {"queued": True},
        },
        ctx,
    )
    assert queued["recipe"]["queuedAt"]
    found = registry.dispatch("search_cookbook", {"query": "", "queued": True}, ctx)
    assert any(r["id"] == recipe["id"] for r in found["results"])
    conn.close()
