"""Migrations are ordered by PRAGMA user_version."""

from __future__ import annotations

from festin.schema import MIGRATIONS, SCHEMA_VERSION, apply, connect


def test_v1_upgrades_to_current_and_apply_twice_is_a_noop(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    MIGRATIONS[0](conn)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()

    apply(conn)
    assert SCHEMA_VERSION == 16
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "sessions" in tables
    assert "kitchen_log_events" in tables
    assert "plugin_settings" in tables
    assert "slips" in tables
    assert "household_context" in tables
    recipe_columns = {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
    assert "favourite" in recipe_columns
    assert "queued_at" in recipe_columns
    assert "applies_to_json" in recipe_columns
    assert "cooks_before_log" in recipe_columns
    assert "needs_practice_review" not in recipe_columns
    week_columns = {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}
    assert "weather_json" in week_columns
    assert "slip_quote" in week_columns
    plugin_columns = {row["name"] for row in conn.execute("PRAGMA table_info(plugin_settings)")}
    assert plugin_columns == {"plugin_id", "enabled", "settings_json", "updated_at"}
    session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert session_columns == {
        "id", "chat_id", "turn_json", "pane", "surface", "draft", "created_at", "updated_at",
    }
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(settings)")}
    assert columns == {
        "id",
        "table_name",
        "week_start_day",
        "dinner_hour",
        "updated_at",
        "weather_location",
        "weather_label",
        "weather_latitude",
        "weather_longitude",
        "weather_timezone",
        "model_base_url",
        "model_name",
        "inbox_enabled",
        "inbox_key_hash",
    }
    inbox = conn.execute(
        "SELECT inbox_enabled, inbox_key_hash FROM settings WHERE id = 1"
    ).fetchone()
    assert inbox["inbox_enabled"] == 0
    assert inbox["inbox_key_hash"] == ""
    assert conn.execute("SELECT table_name FROM settings").fetchone()[0] == "Babette's Table"
    weather = conn.execute(
        "SELECT weather_location, weather_latitude, weather_timezone FROM settings WHERE id = 1"
    ).fetchone()
    assert weather["weather_location"] == ""
    assert weather["weather_latitude"] is None
    assert weather["weather_timezone"] == ""
    chat_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chats)")}
    assert "created_at" in chat_columns
    assert "date_approx" in chat_columns
    assert "updated_at" in chat_columns
    model = conn.execute(
        "SELECT model_base_url, model_name FROM settings WHERE id = 1"
    ).fetchone()
    assert model["model_base_url"] == "https://openrouter.ai/api/v1"
    assert model["model_name"] == ""

    first = "\n".join(conn.iterdump())
    apply(conn)
    assert "\n".join(conn.iterdump()) == first
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_v5_database_gains_plugin_tables_at_v7(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:5]:
        step(conn)
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "kitchen_log_events" in tables
    assert "plugin_settings" in tables
    assert "slips" in tables
    conn.close()


def test_v7_database_gains_favourite_at_v8(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:7]:
        step(conn)
    conn.execute("PRAGMA user_version = 7")
    conn.execute(
        """
        INSERT INTO recipes (
            id, title, kind, voice, source, provenance, status, stub,
            needs_practice_review, ingredients_json, updated_at
        ) VALUES ('CBK-0001', 'Soup', 'recipe', 'zk', 'unknown', 'documented', 'draft', 0, 0, '[]', '2026-01-01T00:00:00Z')
        """
    )
    conn.commit()
    assert "favourite" not in {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    row = conn.execute("SELECT favourite FROM recipes WHERE id = 'CBK-0001'").fetchone()
    assert row["favourite"] == 0
    conn.close()


def test_v4_adds_chat_created_at_on_existing_rows(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:3]:
        step(conn)
    conn.execute("PRAGMA user_version = 3")
    conn.execute(
        "INSERT INTO chats (id, title, ordinal, imported_active, updated_at) VALUES ('c1', 'Old', 0, 0, NULL)"
    )
    conn.commit()
    assert "created_at" not in {row["name"] for row in conn.execute("PRAGMA table_info(chats)")}

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    row = conn.execute("SELECT created_at, date_approx, updated_at FROM chats WHERE id = 'c1'").fetchone()
    assert row["created_at"] is None
    assert row["date_approx"] == 0
    assert row["updated_at"] is None
    model = conn.execute("SELECT model_base_url FROM settings WHERE id = 1").fetchone()
    assert model["model_base_url"] == "https://openrouter.ai/api/v1"
    conn.close()


def test_v6_adds_log_events_and_week_weather(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:4]:
        step(conn)
    conn.execute("PRAGMA user_version = 4")
    conn.execute(
        "INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at) VALUES ('2026-04-18', '', '', NULL, NULL)"
    )
    conn.commit()
    assert "weather_json" not in {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert "weather_json" in {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}
    assert conn.execute("SELECT weather_json FROM weeks WHERE start_date = '2026-04-18'").fetchone()[0] is None
    kinds = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'kitchen_log_events'"
    ).fetchone()[0]
    assert "recipe_added" in kinds
    assert "note_created" in kinds
    assert "recipe_cooked" in kinds
    assert "note_archived" in kinds
    assert "recipe_favourited" in kinds
    assert "photo_added" in kinds
    assert "recipe_planned" in kinds
    assert "queued_at" in {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
    conn.close()


def test_v8_database_widens_log_kinds_at_v9(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:8]:
        step(conn)
    conn.execute("PRAGMA user_version = 8")
    conn.execute(
        """
        INSERT INTO kitchen_log_events (kind, at, ref_id, title, detail, extra_json)
        VALUES ('recipe_added', '2026-04-18T12:00:00.000000Z', 'CBK-0001', 'Soup', '', '{}')
        """
    )
    conn.commit()
    old_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'kitchen_log_events'"
    ).fetchone()[0]
    assert "recipe_cooked" not in old_sql

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    kinds = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'kitchen_log_events'"
    ).fetchone()[0]
    assert "recipe_cooked" in kinds
    assert "photo_added" in kinds
    row = conn.execute(
        "SELECT kind, ref_id FROM kitchen_log_events WHERE ref_id = 'CBK-0001'"
    ).fetchone()
    assert row["kind"] == "recipe_added"
    conn.execute(
        """
        INSERT INTO kitchen_log_events (kind, at, ref_id, title, detail, extra_json)
        VALUES ('recipe_cooked', '2026-04-19T12:00:00.000000Z', 'CBK-0001', 'Soup', '', '{}')
        """
    )
    conn.commit()
    assert (
        conn.execute(
            "SELECT count(*) FROM kitchen_log_events WHERE kind = 'recipe_cooked'"
        ).fetchone()[0]
        == 1
    )
    conn.close()


def test_v10_moves_slip_title_into_slip_quote(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:9]:
        step(conn)
    conn.execute("PRAGMA user_version = 9")
    quote = "Que la chaleur de la table console et rassemble."
    conn.execute(
        """
        INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at)
        VALUES ('2026-10-17', ?, '', NULL, NULL)
        """,
        (quote,),
    )
    conn.execute(
        "INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at)"
        " VALUES ('2026-10-24', 'LE FESTIN', '', NULL, NULL)"
    )
    conn.commit()
    assert "slip_quote" not in {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    week_columns = {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}
    assert "slip_quote" in week_columns
    assert "inbox_enabled" in {
        row["name"] for row in conn.execute("PRAGMA table_info(settings)")
    }
    row = conn.execute(
        "SELECT slip_title, slip_quote FROM weeks WHERE start_date = '2026-10-17'"
    ).fetchone()
    assert row["slip_title"] == ""
    assert row["slip_quote"] == quote
    default = conn.execute(
        "SELECT slip_title, slip_quote FROM weeks WHERE start_date = '2026-10-24'"
    ).fetchone()
    assert (default["slip_title"], default["slip_quote"]) == ("", "")
    conn.close()


def test_v13_moves_context_notes_into_household_context(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:12]:
        step(conn)
    conn.execute("PRAGMA user_version = 12")
    stamp = "2026-10-19T12:00:00.000000Z"
    conn.execute(
        """
        INSERT INTO notes (
            id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
        ) VALUES
            ('context-household', 'household', 'Three at the table.', 'none', NULL, 0, NULL, NULL, NULL, ?),
            ('context-preferences', 'preferences', 'Likes soup.', 'none', NULL, 0, NULL, NULL, NULL, NULL),
            ('context-restrictions', 'restrictions', 'No shellfish.', 'none', NULL, 0, NULL, NULL, NULL, NULL),
            ('note-1', 'shopping', 'cream', 'green', NULL, 1, '2026-10-18', NULL, NULL, ?)
        """,
        (stamp, stamp),
    )
    conn.execute(
        """
        INSERT INTO kitchen_log_events (kind, at, ref_id, title, detail, extra_json)
        VALUES ('note_created', ?, 'context-household', 'Three at the table.', 'household', '{}')
        """,
        (stamp,),
    )
    conn.commit()

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    rows = {
        row["section"]: row
        for row in conn.execute("SELECT section, text, updated_at FROM household_context")
    }
    assert rows["household"]["text"] == "Three at the table."
    assert rows["household"]["updated_at"] == stamp
    assert rows["preferences"]["text"] == "Likes soup."
    assert rows["restrictions"]["text"] == "No shellfish."
    assert (
        conn.execute(
            "SELECT count(*) FROM notes WHERE id LIKE 'context-%'"
        ).fetchone()[0]
        == 0
    )
    assert conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 1
    assert (
        conn.execute(
            "SELECT count(*) FROM kitchen_log_events WHERE ref_id LIKE 'context-%'"
        ).fetchone()[0]
        == 0
    )
    conn.close()


def test_v14_renames_recipe_to_formule_and_moves_praxis_applies_to(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:13]:
        step(conn)
    conn.execute("PRAGMA user_version = 13")
    conn.execute(
        """
        INSERT INTO recipes (
            id, title, kind, category, voice, source, provenance, status, stub,
            needs_practice_review, favourite, search_description, method, notes,
            context, ocr_text, ingredients_json, tattva_json, photos_json,
            created_at, updated_at, extra_json
        ) VALUES
            ('CBK-0001', 'Soup', 'recipe', 'soups-stews', 'zk', '', 'documented', 'ok', 0,
             0, 0, '', 'Simmer.', '', '', '', '["water","salt"]', '[]', '[]',
             '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}'),
            ('CBK-0002', 'Mint', 'praxis', 'misc', 'zk', '', 'documented', 'ok', 0,
             0, 0, '', 'Whip egg white with sugar.', '', '', '',
             '["mint","egg white","sugar"]', '[]', '[]',
             '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z', '{}')
        """
    )
    conn.commit()

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    soup = conn.execute("SELECT kind, ingredients_json, applies_to_json FROM recipes WHERE id = 'CBK-0001'").fetchone()
    mint = conn.execute("SELECT kind, ingredients_json, applies_to_json FROM recipes WHERE id = 'CBK-0002'").fetchone()
    assert soup["kind"] == "formule"
    assert soup["ingredients_json"] == '["water","salt"]'
    assert soup["applies_to_json"] == "[]"
    assert mint["kind"] == "praxis"
    assert mint["ingredients_json"] == "[]"
    assert mint["applies_to_json"] == '["mint","egg white","sugar"]'
    assert "queued_at" in {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
    # CHECK rejects the old kind name.
    try:
        conn.execute(
            "INSERT INTO recipes (id, title, kind) VALUES ('CBK-9', 'Nope', 'recipe')"
        )
        raise AssertionError("expected CHECK failure for kind=recipe")
    except Exception:
        conn.rollback()
    conn.close()


def test_v16_carries_cleared_review_without_event_as_cooks_before_log(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    for step in MIGRATIONS[:15]:
        step(conn)
    conn.execute("PRAGMA user_version = 15")
    conn.execute(
        """
        INSERT INTO recipes (
            id, title, kind, category, voice, source, provenance, status, stub,
            needs_practice_review, favourite, queued_at, search_description, method, notes,
            context, ocr_text, ingredients_json, applies_to_json, tattva_json,
            photos_json, created_at, updated_at, extra_json
        ) VALUES
            ('CBK-0001', 'Carried', 'formule', 'soups-stews', '', '', 'documented', 'ok', 0,
             0, 0, NULL, '', '', '', '', '', '[]', '[]', '[]', '[]',
             '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}'),
            ('CBK-0002', 'Still review', 'formule', 'soups-stews', '', '', 'documented', 'ok', 0,
             1, 0, NULL, '', '', '', '', '', '[]', '[]', '[]', '[]',
             '2026-01-02T00:00:00Z', '2026-01-02T00:00:00Z', '{}'),
            ('CBK-0003', 'Logged cook', 'formule', 'soups-stews', '', '', 'documented', 'ok', 0,
             0, 0, NULL, '', '', '', '', '', '[]', '[]', '[]', '[]',
             '2026-01-03T00:00:00Z', '2026-01-03T00:00:00Z', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO kitchen_log_events (kind, at, ref_id, title, detail, extra_json)
        VALUES ('recipe_cooked', '2026-01-04T12:00:00Z', 'CBK-0003', 'Logged cook',
                '2026-01-04', '{"date":"2026-01-04"}')
        """
    )
    conn.commit()

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
    assert "cooks_before_log" in cols
    assert "needs_practice_review" not in cols
    by_id = {
        row["id"]: row["cooks_before_log"]
        for row in conn.execute("SELECT id, cooks_before_log FROM recipes")
    }
    assert by_id == {"CBK-0001": 1, "CBK-0002": 0, "CBK-0003": 0}
    conn.close()
