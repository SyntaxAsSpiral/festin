"""Migrations are ordered by PRAGMA user_version."""

from __future__ import annotations

from festin.schema import MIGRATIONS, SCHEMA_VERSION, apply, connect


def test_v1_upgrades_to_current_and_apply_twice_is_a_noop(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    MIGRATIONS[0](conn)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()

    apply(conn)
    assert SCHEMA_VERSION == 6
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "sessions" in tables
    assert "kitchen_log_events" in tables
    assert "plugin_settings" not in tables
    week_columns = {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}
    assert "weather_json" in week_columns
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
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
    assert "weather_json" in {row["name"] for row in conn.execute("PRAGMA table_info(weeks)")}
    assert conn.execute("SELECT weather_json FROM weeks WHERE start_date = '2026-04-18'").fetchone()[0] is None
    kinds = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'kitchen_log_events'"
    ).fetchone()[0]
    assert "recipe_added" in kinds
    assert "note_created" in kinds
    conn.close()
