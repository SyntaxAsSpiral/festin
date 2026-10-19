"""Core settings round-trip, today in the stored zone, and week bounds."""

from __future__ import annotations

import io
import json
from datetime import date, datetime, timezone
from unittest.mock import patch
from urllib.error import URLError

import pytest

from festin.schema import connect
from festin import settings as core


def _geocode_payload():
    return {
        "results": [
            {
                "name": "Hayden",
                "admin1": "Idaho",
                "country": "United States",
                "latitude": 47.76602,
                "longitude": -116.78658,
                "timezone": "America/Los_Angeles",
            }
        ]
    }


def _response(payload: dict):
    return io.BytesIO(json.dumps(payload).encode())


@pytest.fixture
def conn(blank_db):
    db = connect(blank_db)
    yield db
    db.close()


def test_settings_round_trip(conn):
    got = core.get_settings(conn)
    assert got["table_name"] == "Babette's Table"
    assert got["week_start_day"] == "sat"
    assert got["dinner_hour"] == "17:30"
    assert got["weather"] == {"location": ""}

    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_geocode_payload())
        saved = core.update_settings(
            conn,
            table_name="Holliday Table",
            dinner_hour="18:00",
            week_start_day="mon",
            weather_location="83835",
        )
    assert saved["table_name"] == "Holliday Table"
    assert saved["dinner_hour"] == "18:00"
    assert saved["week_start_day"] == "mon"
    assert saved["weather"]["location"] == "83835"
    assert saved["weather"]["latitude"] == 47.76602
    assert saved["weather"]["longitude"] == -116.78658
    assert saved["weather"]["timezone"] == "America/Los_Angeles"
    assert saved["weather"]["label"] == "Hayden, Idaho, United States"
    assert saved["updated_at"]

    again = core.get_settings(conn)
    assert again == saved

    # Same location string: no second geocode.
    with patch("festin.weather.urlopen") as urlopen:
        core.update_settings(conn, weather_location="83835", dinner_hour="19:15")
        urlopen.assert_not_called()
    assert core.get_settings(conn)["dinner_hour"] == "19:15"
    assert core.get_settings(conn)["weather"]["latitude"] == 47.76602


def test_bad_weather_location_keeps_live_error(conn):
    with patch("festin.weather.urlopen", side_effect=URLError("down")):
        with pytest.raises(ValueError, match="could not be found") as err:
            core.update_settings(conn, weather_location="not-a-place")
    assert str(err.value) == (
        "That weather location could not be found. Try a city and state or postal code."
    )
    assert core.get_settings(conn)["weather"] == {"location": ""}


def test_today_follows_stored_timezone(conn):
    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_geocode_payload())
        core.update_settings(conn, weather_location="83835")

    # 2026-10-19 01:30 UTC is still 2026-10-18 evening in America/Los_Angeles.
    instant = datetime(2026, 10, 19, 1, 30, tzinfo=timezone.utc)
    assert core.today(conn, now=instant) == date(2026, 10, 18)

    # No stored zone: fall back to the server's local zone.
    core.update_settings(conn, weather_location="")
    assert core.today(conn, now=instant) == instant.astimezone().date()


def test_week_bounds_from_configured_start(conn):
    # Wednesday 2026-10-14 with Saturday start → Sat 10/10 … Fri 10/16.
    core.update_settings(conn, week_start_day="sat")
    start, end = core.week_bounds(conn, on=date(2026, 10, 14))
    assert start == date(2026, 10, 10)
    assert end == date(2026, 10, 16)

    # Monday start: Wed 10/14 → Mon 10/12 … Sun 10/18.
    core.update_settings(conn, week_start_day="mon")
    start, end = core.week_bounds(conn, on=date(2026, 10, 14))
    assert start == date(2026, 10, 12)
    assert end == date(2026, 10, 18)

    # The start day itself is the first day of its week.
    assert core.week_start_for(date(2026, 10, 12), "mon") == date(2026, 10, 12)
    assert core.week_bounds(conn, on=date(2026, 10, 12))[0] == date(2026, 10, 12)
