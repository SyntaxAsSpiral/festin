"""Dinner tattva plugin: local sunrise cycles, Log colour, chat opening. No outside calls."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from io import BytesIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from festin import log as kitchen_log
from festin import plans
from festin.chat.registry import ToolRegistry
from festin.plugins import host
from festin.plugins.tattva import compute
from festin.plugins.tattva.plugin import PLUGIN
from festin.schema import connect


class Ctx:
    def __init__(self, conn):
        self.conn = conn


def _place():
    # Hayden / Coeur d'Alene area, matching sideriod gnomon tests.
    return {"lat": 47.6777, "lon": -116.7805, "tz": "America/Los_Angeles"}


def _enable(conn, *, dinner="17:30", sideriod=""):
    host.update_plugin(
        conn,
        "tattva",
        {"enabled": True, "settings": {"dinnerHour": dinner, "sideriodUrl": sideriod}},
    )


def _set_weather(conn, place):
    conn.execute(
        """
        UPDATE settings SET
            weather_location = ?,
            weather_label = ?,
            weather_latitude = ?,
            weather_longitude = ?,
            weather_timezone = ?
        WHERE id = 1
        """,
        ("83835", "Hayden, Idaho", place["lat"], place["lon"], place["tz"]),
    )
    conn.commit()


def test_local_cycle_from_sunrise():
    compute.clear_cache()
    place = _place()
    tz = ZoneInfo(place["tz"])
    day = date(2026, 9, 21)  # Monday → DAY_START Apas
    sunrise = compute.noaa_sun_event(day, place["lat"], place["lon"], tz, "rise")
    assert sunrise is not None
    # First segment after sunrise is the day-start element.
    just_after = sunrise + timedelta(minutes=1)
    row = compute.local_tattwa(just_after, place["lat"], place["lon"], tz)
    assert row["element"] == "Apas"
    # 24 minutes later advances one step in the standard sequence.
    next_seg = sunrise + timedelta(minutes=25)
    row2 = compute.local_tattwa(next_seg, place["lat"], place["lon"], tz)
    assert row2["element"] == "Tejas"


def test_dinner_nights_local_and_weekday_fallback():
    compute.clear_cache()
    days = [date(2026, 9, 21) + timedelta(days=i) for i in range(5)]
    local = compute.dinner_nights(days, "17:30", _place())
    assert all(row["source"] == "local" for row in local)
    assert all(row["element"] in compute.ELEMENTS for row in local)
    fallen = compute.dinner_nights(days, "17:30", None)
    assert [row["element"] for row in fallen] == ["Apas", "Tejas", "Prithvi", "Akasha", "Apas"]
    assert all(row["source"] == "weekday fallback" for row in fallen)
    line = compute.context_line(days, "17:30", None)
    assert line.startswith("Dinner tattva (weekday fallback):")
    assert "Mon 9/21 Apas" in line


def test_week_tint_and_look():
    compute.clear_cache()
    tint = compute.week_tint("2026-09-19", "17:30", None)  # Saturday → Vayu
    assert tint["name"] == "Vayu"
    assert tint["glyph"] == "🜁"
    assert tint["colour"] == "#7a88b0"
    assert tint["source"] == "weekday fallback"


def test_optional_sideriod_uses_injected_urlopen_never_network():
    compute.clear_cache()
    day = date(2026, 9, 21)
    dinner = datetime(2026, 9, 21, 17, 30)
    later = dinner + timedelta(minutes=24)
    payload = {
        "lat": 47.6777,
        "lon": -116.7805,
        "tz": "America/Los_Angeles",
        "results": [
            {
                "at": dinner.isoformat(),
                "name": "Apas",
                "starts_at": dinner.isoformat(),
                "ends_at": (dinner + timedelta(minutes=20)).isoformat(),
            },
            {
                "at": later.isoformat(),
                "name": "Tejas",
                "starts_at": later.isoformat(),
                "ends_at": (later + timedelta(minutes=24)).isoformat(),
            },
        ],
    }

    class _JsonResp:
        def __init__(self, body):
            self._body = body

        def __enter__(self):
            return BytesIO(json.dumps(self._body).encode())

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=2):
        assert "127.0.0.1:9" in request.full_url
        return _JsonResp(payload)

    with patch.object(compute, "_urlopen", fake_urlopen):
        rows = compute.dinner_nights(
            [day],
            "17:30",
            _place(),
            sideriod_url="http://127.0.0.1:9",
        )
    assert rows[0]["source"] == "sideriod"
    assert rows[0]["element"] == "Apas"
    assert "turning Tejas" in rows[0]["phrase"]


def test_sideriod_failure_falls_back_to_local(blank_db):
    compute.clear_cache()

    def boom(request, timeout=2):
        raise TimeoutError("nope")

    with patch.object(compute, "_urlopen", boom):
        rows = compute.dinner_nights(
            [date(2026, 9, 21)],
            "17:30",
            _place(),
            sideriod_url="http://127.0.0.1:9/api/tattwa",
        )
    assert rows[0]["source"] == "local"
    assert rows[0]["element"] in compute.ELEMENTS


def test_plugin_off_leaves_log_untinted(blank_db):
    compute.clear_cache()
    conn = connect(blank_db)
    week = "2026-09-19"
    plans.save_plan(
        conn,
        week,
        {
            "weekStart": week,
            "slipTitle": "LE FESTIN",
            "days": [
                {
                    "date": (date.fromisoformat(week) + timedelta(days=i)).isoformat(),
                    "title": "",
                    "recipe": None,
                }
                for i in range(7)
            ],
        },
    )
    assert kitchen_log.week_tattva(conn, week) is None
    body = kitchen_log.list_log(conn)
    entry = next(item for item in body["entries"] if item["kind"] == "week")
    assert entry["tattva"] is None


def test_plugin_on_colours_log_and_opens_chat(blank_db):
    compute.clear_cache()
    conn = connect(blank_db)
    _set_weather(conn, _place())
    _enable(conn, dinner="17:30")
    week = "2026-09-19"
    tint = kitchen_log.week_tattva(conn, week)
    assert tint is not None
    assert tint["name"] in compute.ELEMENTS
    assert tint["glyph"]
    assert tint["colour"].startswith("#")

    public = host.get_plugin(conn, "tattva")
    assert public["enabled"] is True
    assert public["settings"]["dinnerHour"] == "17:30"
    assert public["settings"]["sideriodUrl"] == ""
    assert public["name"] == "Dinner tattva"

    registry = ToolRegistry()
    PLUGIN.register(registry)
    with patch("festin.plugins.tattva.plugin.weather_forecast") as forecast:
        forecast.return_value = {
            "status": "ok",
            "days": [{"date": (date(2026, 9, 21) + timedelta(days=i)).isoformat()} for i in range(5)],
        }
        snippets = registry.opening_snippets(Ctx(conn))
    assert len(snippets) == 1
    assert "Dinner tattva" in snippets[0]
    assert "Honor operator requests" in snippets[0]

    # Bad dinner hour rejected.
    try:
        host.update_plugin(conn, "tattva", {"settings": {"dinnerHour": "25:99"}})
        assert False, "expected ValueError"
    except ValueError as err:
        assert "17:30" in str(err)

    feed = host.feed("tattva")
    assert set(feed["elements"]) == set(compute.ELEMENTS)
    assert feed["look"]["Tejas"]["glyph"] == "🜂"


def test_plugins_list_includes_tattva_off_by_default(blank_db):
    conn = connect(blank_db)
    listed = host.list_plugins(conn)
    ids = [item["id"] for item in listed]
    assert ids == ["printer", "tattva", "outbound", "voice"]
    tattva = next(item for item in listed if item["id"] == "tattva")
    assert tattva["enabled"] is False
    assert tattva["settings"]["dinnerHour"] == "17:30"
    # Tools stay printer-only; tattva contributes opening text only.
    _enable(conn)
    names = host.build_registry(conn).names()
    assert "prepare_slip" not in names  # printer still off
    assert host.build_registry(conn).opening_snippets(Ctx(conn))  # tattva on


def test_import_seeds_plugin_dinner_hour(tmp_path, blank_db):
    from festin.importer import _seed_tattva_dinner_hour

    conn = connect(blank_db)
    _seed_tattva_dinner_hour(conn, "18:45")
    conn.commit()
    row = conn.execute(
        "SELECT enabled, settings_json FROM plugin_settings WHERE plugin_id = ?",
        ("tattva",),
    ).fetchone()
    assert row is not None
    assert row["enabled"] == 0
    settings = json.loads(row["settings_json"])
    assert settings["dinnerHour"] == "18:45"
