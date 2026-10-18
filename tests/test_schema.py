"""Migrations are ordered by PRAGMA user_version."""

from __future__ import annotations

from festin.schema import MIGRATIONS, SCHEMA_VERSION, apply, connect


def test_v1_upgrades_to_current_and_apply_twice_is_a_noop(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    MIGRATIONS[0](conn)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()

    apply(conn)
    assert SCHEMA_VERSION == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "sessions" not in tables
    assert "plugin_settings" not in tables
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
    }
    assert conn.execute("SELECT table_name FROM settings").fetchone()[0] == "Babette's Table"
    weather = conn.execute(
        "SELECT weather_location, weather_latitude, weather_timezone FROM settings WHERE id = 1"
    ).fetchone()
    assert weather["weather_location"] == ""
    assert weather["weather_latitude"] is None
    assert weather["weather_timezone"] == ""

    first = "\n".join(conn.iterdump())
    apply(conn)
    assert "\n".join(conn.iterdump()) == first
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
