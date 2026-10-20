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


def test_cooked_clears_queue_without_slip_overwrite(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {
            "title": "Missed Roast",
            "ingredients": ["beef"],
            "category": "meats",
            "queued": True,
        },
    )
    assert status == 201
    assert "needsPracticeReview" not in recipe
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
    assert cooked["queuedAt"] is None
    assert cooked["cookCount"] == 1
    assert "needsPracticeReview" not in cooked

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


def test_slip_toggle_clears_queue(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {
            "title": "Slip Clear",
            "ingredients": ["onion"],
            "category": "soups-stews",
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
    assert saved["queuedAt"] is None
    assert saved["cookCount"] == 1
    assert "needsPracticeReview" not in saved

    # Queued again after that cook: re-saving the slip with the night still cooked is
    # not a new cook, so the queue mark stays.
    status, again = client.request(
        "POST",
        "/api/recipes/" + recipe["id"],
        {"expected_updated_at": saved["updatedAt"], "queued": True},
    )
    assert status == 200 and again["queuedAt"]
    plan = plans_mod.get_plan(conn, start.isoformat())
    plans_mod.save_plan(
        conn,
        start.isoformat(),
        {
            "weekStart": start.isoformat(),
            "expected_updated_at": plan["updatedAt"],
            "days": [dict(slot) for slot in plan["days"]],
            "slipTitle": "",
            "notes": "re-saved",
        },
    )
    kept = recipes_mod.get_recipe(conn, recipe["id"])
    conn.close()
    assert kept["queuedAt"]


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


def test_slip_toggle_logs_cook_without_review(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Plain Night", "ingredients": ["salt"], "category": "soups-stews"},
    )
    assert status == 201
    assert "needsPracticeReview" not in recipe
    assert recipe["queuedAt"] is None

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
    assert saved["cookCount"] == 1
    assert saved["lastCooked"] == day.isoformat()

    status, body = client.request("GET", "/api/log")
    cooks = [
        e for e in body["entries"] if e.get("kind") == "recipe_cooked" and e.get("id") == recipe["id"]
    ]
    assert len(cooks) == 1
    assert cooks[0]["ordinal"] == 1
    assert cooks[0]["date"] == day.isoformat()


def test_cooked_button_then_same_night_does_not_double(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Once Only", "ingredients": ["egg"], "category": "eggs", "queued": True},
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
            "slipTitle": "",
            "notes": "",
        },
    )
    fresh = recipes_mod.get_recipe(conn, recipe["id"])
    conn.close()

    status, cooked = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/cooked",
        {"expected_updated_at": fresh["updatedAt"]},
    )
    assert status == 200
    assert cooked["cookCount"] == 1

    conn = connect(kitchen.db_path)
    plan = plans_mod.get_plan(conn, start.isoformat())
    plans_mod.save_plan(
        conn,
        start.isoformat(),
        {
            "weekStart": start.isoformat(),
            "expected_updated_at": plan["updatedAt"],
            "days": [dict(slot) for slot in plan["days"]],
            "slipTitle": "",
            "notes": "re-save after button",
        },
    )
    again = recipes_mod.get_recipe(conn, recipe["id"])
    conn.close()
    assert again["cookCount"] == 1

    status, body = client.request("GET", "/api/log")
    cooks = [
        e for e in body["entries"] if e.get("kind") == "recipe_cooked" and e.get("id") == recipe["id"]
    ]
    assert len(cooks) == 1
    assert cooks[0]["ordinal"] == 1


def test_second_cook_raises_count_and_ordinal(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Twice Soup", "ingredients": ["stock"], "category": "soups-stews"},
    )
    assert status == 201

    status, first = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/cooked",
        {"expected_updated_at": recipe["updatedAt"]},
    )
    assert status == 200
    assert first["cookCount"] == 1

    # Same calendar day is one cook (distinct recipe, date), even with two events.
    status, same_day = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/cooked",
        {"expected_updated_at": first["updatedAt"]},
    )
    assert status == 200
    assert same_day["cookCount"] == 1

    # A cook dated another day raises the count; both Log lines share ordinals by date.
    conn = connect(kitchen.db_path)
    from festin import log as kitchen_log

    kitchen_log.record_event(
        conn,
        "recipe_cooked",
        ref_id=recipe["id"],
        at="2026-10-01T19:00:00.000000Z",
        title="Twice Soup",
        detail="2026-10-01",
        extra={"date": "2026-10-01", "category": "soups-stews"},
    )
    conn.commit()
    second = recipes_mod.get_recipe(conn, recipe["id"])
    conn.close()
    assert second["cookCount"] == 2
    assert second["lastCooked"]

    status, body = client.request("GET", "/api/log")
    cooks = [
        e
        for e in body["entries"]
        if e.get("kind") == "recipe_cooked" and e.get("id") == recipe["id"]
    ]
    by_date = {e.get("date"): e.get("ordinal") for e in cooks}
    assert by_date.get("2026-10-01") == 1
    # Today's button events share one ordinal (the later date in the set).
    today_ordinals = {e.get("ordinal") for e in cooks if e.get("date") and e.get("date") != "2026-10-01"}
    assert today_ordinals == {2}


def test_ended_week_linked_night_counts_as_cook_with_dedupe(blank_db):
    """A cook is a distinct (recipe, date): events ∪ ended-week linked nights."""
    conn = connect(blank_db)
    recipe = recipes_mod.create_recipe(
        conn,
        {"title": "Ended Link", "ingredients": ["a"], "category": "soups-stews"},
    )
    # Past week (Log boxes it): linked night, never ticked cooked.
    conn.execute(
        """
        INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
        VALUES ('2026-09-26', 'Sep', '', NULL, '2026-09-26T12:00:00.000000Z', NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO nights (date, week_start, recipe_id, title, cooked, updated_at)
        VALUES ('2026-09-28', '2026-09-26', ?, 'Ended Link', 0, '2026-09-28T12:00:00.000000Z')
        """,
        (recipe["id"],),
    )
    conn.commit()

    stats = recipes_mod.cook_stats_for(conn, [recipe["id"]])[recipe["id"]]
    assert stats["cookCount"] == 1
    assert stats["lastCooked"] == "2026-09-28"

    # Carried pre-log cook with no dated event: count without lastCooked.
    carried = recipes_mod.create_recipe(
        conn,
        {"title": "Carried Once", "ingredients": ["b"], "category": "soups-stews"},
    )
    conn.execute(
        "UPDATE recipes SET cooks_before_log = 1 WHERE id = ?",
        (carried["id"],),
    )
    conn.commit()
    carried_stats = recipes_mod.cook_stats_for(conn, [carried["id"]])[carried["id"]]
    assert carried_stats["cookCount"] == 1
    assert carried_stats["lastCooked"] is None
    public = recipes_mod.get_recipe(conn, carried["id"])
    assert public["cookCount"] == 1
    assert public["lastCooked"] is None
    assert "needsPracticeReview" not in public

    # Same date as a recipe_cooked event: still one cook.
    from festin import log as kitchen_log

    kitchen_log.record_event(
        conn,
        "recipe_cooked",
        ref_id=recipe["id"],
        at="2026-09-28T19:00:00.000000Z",
        title="Ended Link",
        detail="2026-09-28",
        extra={"date": "2026-09-28", "category": "soups-stews"},
    )
    conn.commit()
    stats = recipes_mod.cook_stats_for(conn, [recipe["id"]])[recipe["id"]]
    assert stats["cookCount"] == 1

    # A later Cooked-button event adds a second cook.
    kitchen_log.record_event(
        conn,
        "recipe_cooked",
        ref_id=recipe["id"],
        at="2026-10-18T19:00:00.000000Z",
        title="Ended Link",
        detail="2026-10-18",
        extra={"date": "2026-10-18", "category": "soups-stews"},
    )
    conn.commit()
    dates = recipes_mod.cook_dates_for(conn, [recipe["id"]])[recipe["id"]]
    assert dates == ["2026-09-28", "2026-10-18"]
    stats = recipes_mod.cook_stats_for(conn, [recipe["id"]])[recipe["id"]]
    assert stats["cookCount"] == 2
    assert stats["lastCooked"] == "2026-10-18"

    # Current-week linked night does not count until the week ends.
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
            "slipTitle": "",
            "notes": "",
        },
    )
    stats = recipes_mod.cook_stats_for(conn, [recipe["id"]])[recipe["id"]]
    assert stats["cookCount"] == 2

    # Log ordinal for the later event is 2 in the unified set.
    from festin import log as log_mod

    page = log_mod.list_log(conn, limit=40)
    cooks = [
        e
        for e in page["entries"]
        if e.get("kind") == "recipe_cooked" and e.get("id") == recipe["id"]
    ]
    by_date = {e.get("date"): e.get("ordinal") for e in cooks}
    assert by_date.get("2026-09-28") == 1
    assert by_date.get("2026-10-18") == 2
    # Ended night alone wrote no extra Log line beyond the event we inserted.
    assert len(cooks) == 2
    conn.close()


def test_close_ended_weeks_clears_stale_queue_only(blank_db):
    conn = connect(blank_db)
    before = recipes_mod.create_recipe(
        conn,
        {"title": "Queued Before", "ingredients": ["a"], "category": "soups-stews", "queued": True},
        now=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    after = recipes_mod.create_recipe(
        conn,
        {"title": "Queued After", "ingredients": ["b"], "category": "soups-stews", "queued": True},
        now=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
    )
    current = recipes_mod.create_recipe(
        conn,
        {"title": "Current Week", "ingredients": ["c"], "category": "soups-stews", "queued": True},
        now=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
    )
    assert before["queuedAt"] and after["queuedAt"] and current["queuedAt"]

    day = today(conn)
    start = week_start_for(day, get_settings(conn)["week_start_day"])
    conn.execute(
        """
        INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
        VALUES
          ('2026-09-26', 'Sep', '', NULL, '2026-09-26T12:00:00.000000Z', NULL),
          (?, 'Now', '', NULL, ?, NULL)
        """,
        (start.isoformat(), day.isoformat() + "T12:00:00.000000Z"),
    )
    conn.execute(
        """
        INSERT INTO nights (date, week_start, recipe_id, title, cooked, updated_at)
        VALUES
          ('2026-09-28', '2026-09-26', ?, 'Queued Before', 0, '2026-09-28T12:00:00.000000Z'),
          ('2026-09-29', '2026-09-26', ?, 'Queued After', 0, '2026-09-29T12:00:00.000000Z'),
          (?, ?, ?, 'Current Week', 0, ?)
        """,
        (
            before["id"],
            after["id"],
            day.isoformat(),
            start.isoformat(),
            current["id"],
            day.isoformat() + "T12:00:00.000000Z",
        ),
    )
    conn.commit()

    cleared = recipes_mod.close_ended_weeks(conn)
    assert cleared == 1
    assert recipes_mod.close_ended_weeks(conn) == 0  # idempotent

    # Avoid get_recipe here (it sweeps again); read queued_at directly.
    def queued(rid):
        return conn.execute("SELECT queued_at FROM recipes WHERE id = ?", (rid,)).fetchone()[0]

    assert queued(before["id"]) is None
    assert queued(after["id"])  # queued after the ended night
    assert queued(current["id"])  # current-week link does not clear
    conn.close()


def test_babette_cooked_true_matches_button(blank_db, tmp_path):
    from datetime import date
    from pathlib import Path

    from festin.chat.core_tools import build_core_registry
    from festin.chat.messages import ensure_chat

    class Ctx:
        def __init__(self, conn, data_dir, today_value):
            self.conn = conn
            self.data_dir = Path(data_dir)
            self.chat_id = "chat-cook"
            self.today = today_value

    conn = connect(blank_db)
    data_dir = tmp_path / "data"
    (data_dir / "photos").mkdir(parents=True)
    ensure_chat(conn, "chat-cook")
    registry = build_core_registry()
    day = date(2026, 10, 18)
    ctx = Ctx(conn, data_dir, day)
    added = registry.dispatch(
        "add_recipe",
        {
            "title": "Babette Cook",
            "ingredients": ["beans"],
            "category": "soups-stews",
            "searchDescription": "A pot.",
            "queued": True,
        },
        ctx,
    )
    recipe = added["recipe"]
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
            "slipTitle": "",
            "notes": "",
        },
    )
    fresh = recipes_mod.get_recipe(conn, recipe["id"])

    cooked = registry.dispatch(
        "edit_recipe",
        {
            "recipe_id": recipe["id"],
            "expected_updated_at": fresh["updatedAt"],
            "changes": {"cooked": True},
        },
        ctx,
    )
    assert "needsPracticeReview" not in cooked["recipe"]
    assert cooked["recipe"]["queuedAt"] is None
    assert cooked["recipe"]["cookCount"] == 1
    assert cooked["recipe"]["lastCooked"] == day.isoformat()

    night = conn.execute(
        "SELECT cooked FROM nights WHERE date = ?", (day.isoformat(),)
    ).fetchone()
    assert night["cooked"] == 1

    found = registry.dispatch("search_cookbook", {"query": "Babette Cook"}, ctx)
    card = next(r for r in found["results"] if r["id"] == recipe["id"])
    assert card["cookCount"] == 1
    assert card["lastCooked"] == day.isoformat()

    try:
        registry.dispatch(
            "edit_recipe",
            {
                "recipe_id": recipe["id"],
                "expected_updated_at": cooked["recipe"]["updatedAt"],
                "changes": {"cooked": True, "notes": "nope"},
            },
            ctx,
        )
        assert False, "mixed cooked+notes should fail"
    except ValueError as exc:
        assert "alone" in str(exc).casefold()

    conn.close()


def test_close_ended_weeks_reads_queue_stamp_in_household_time(blank_db):
    # Queued at 6:30 pm Pacific on the 28th: the stamp is already the 29th in UTC.
    # That dinner on the 28th answered it, so the ended week clears it.
    conn = connect(blank_db)
    conn.execute("UPDATE settings SET weather_timezone = 'America/Los_Angeles'")
    conn.commit()
    evening = recipes_mod.create_recipe(
        conn,
        {"title": "Queued At Dusk", "ingredients": ["a"], "category": "soups-stews", "queued": True},
        now=datetime(2026, 9, 29, 1, 30, tzinfo=timezone.utc),
    )
    conn.execute(
        "INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)"
        " VALUES ('2026-09-26', 'Sep', '', NULL, '2026-09-26T12:00:00.000000Z', NULL)"
    )
    conn.execute(
        "INSERT INTO nights (date, week_start, recipe_id, title, cooked, updated_at)"
        " VALUES ('2026-09-28', '2026-09-26', ?, 'Queued At Dusk', 0, '2026-09-28T12:00:00.000000Z')",
        (evening["id"],),
    )
    conn.commit()
    assert recipes_mod.close_ended_weeks(conn) == 1
    assert conn.execute("SELECT queued_at FROM recipes WHERE id = ?", (evening["id"],)).fetchone()[0] is None
    conn.close()
