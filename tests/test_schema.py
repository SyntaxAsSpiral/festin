"""Migrations are ordered by PRAGMA user_version."""

from __future__ import annotations

from festin.schema import MIGRATIONS, SCHEMA_VERSION, apply, connect


def test_v1_upgrades_to_current_and_apply_twice_is_a_noop(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    MIGRATIONS[0](conn)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()

    apply(conn)
    assert SCHEMA_VERSION == 10
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "sessions" in tables
    assert "kitchen_log_events" in tables
    assert "plugin_settings" in tables
    assert "slips" in tables
    recipe_columns = {row["name"] for row in conn.execute("PRAGMA table_info(recipes)")}
    assert "favourite" in recipe_columns
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
    }
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
    conn.commit()
    assert "slip_quote" not in {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}

    apply(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
    week_columns = {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}
    assert "slip_quote" in week_columns
    row = conn.execute(
        "SELECT slip_title, slip_quote FROM weeks WHERE start_date = '2026-10-17'"
    ).fetchone()
    assert row["slip_title"] == ""
    assert row["slip_quote"] == quote
    conn.close()
