"""Weather geocode and forecast. Network is always patched."""

from __future__ import annotations

import io
import json
from unittest.mock import patch
from urllib.error import URLError

import pytest

from festin import weather


def _response(payload: dict):
    raw = json.dumps(payload).encode()
    return io.BytesIO(raw)


@pytest.fixture(autouse=True)
def _clear_weather_cache():
    weather.clear_cache()
    yield
    weather.clear_cache()


def test_resolve_stores_lat_lon_timezone():
    payload = {
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
    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(payload)
        resolved = weather.resolve_weather_location("83835")
    assert resolved == {
        "location": "83835",
        "label": "Hayden, Idaho, United States",
        "latitude": 47.76602,
        "longitude": -116.78658,
        "timezone": "America/Los_Angeles",
    }
    urlopen.assert_called_once()


def test_resolve_bad_location_keeps_live_error():
    with patch("festin.weather.urlopen", side_effect=URLError("down")):
        with pytest.raises(ValueError, match="could not be found") as err:
            weather.resolve_weather_location("nowhere-xyz")
    assert str(err.value) == (
        "That weather location could not be found. Try a city and state or postal code."
    )


def test_resolve_empty_and_too_long():
    assert weather.resolve_weather_location("  ") == {"location": ""}
    with pytest.raises(ValueError, match="under 120 characters"):
        weather.resolve_weather_location("x" * 121)


def test_weather_code_map():
    assert weather.weather_code(0) == "clear"
    assert weather.weather_code(2) == "partly cloudy"
    assert weather.weather_code(3) == "cloudy"
    assert weather.weather_code(45) == "foggy"
    assert weather.weather_code(51) == "drizzly"
    assert weather.weather_code(61) == "rainy"
    assert weather.weather_code(71) == "snowy"
    assert weather.weather_code(95) == "stormy"
    assert weather.weather_code(42) == "mixed"


def test_forecast_maps_codes_and_caches_three_hours():
    settings = {
        "weather": {
            "location": "83835",
            "label": "Hayden, Idaho, United States",
            "latitude": 47.7,
            "longitude": -116.7,
            "timezone": "America/Los_Angeles",
        }
    }
    payload = {
        "daily": {
            "time": ["2026-10-18", "2026-10-19"],
            "weather_code": [0, 61],
            "temperature_2m_min": [40.2, 38.8],
            "temperature_2m_max": [55.4, 50.1],
            "precipitation_probability_max": [10, 80],
        }
    }
    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(payload)
        with patch("festin.weather.time.monotonic", side_effect=[1000.0, 1000.0, 1001.0, 1001.0]):
            first = weather.weather_forecast(settings)
            second = weather.weather_forecast(settings)
    assert urlopen.call_count == 1
    assert first == second
    assert first["status"] == "ok"
    assert first["location"] == "Hayden, Idaho, United States"
    assert first["days"][0] == {
        "date": "2026-10-18",
        "conditions": "clear",
        "low_f": 40,
        "high_f": 55,
        "rain_chance_pct": 10,
    }
    assert first["days"][1]["conditions"] == "rainy"

    # Still inside the 3 h window: no new fetch.
    with patch("festin.weather.urlopen") as urlopen:
        with patch("festin.weather.time.monotonic", return_value=1000.0 + 3 * 60 * 60 - 1):
            weather.weather_forecast(settings)
        urlopen.assert_not_called()

    # Past the window: fetch again.
    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(payload)
        with patch("festin.weather.time.monotonic", side_effect=[1000.0 + 3 * 60 * 60, 1000.0 + 3 * 60 * 60]):
            weather.weather_forecast(settings)
        urlopen.assert_called_once()


def test_forecast_unavailable_and_not_configured():
    assert weather.weather_forecast({"weather": {"location": ""}}) == {"status": "not configured"}
    assert weather.weather_forecast({}) == {"status": "not configured"}
    assert weather.weather_forecast({"weather": {"location": "83835"}}) == {
        "status": "unavailable",
        "location": "83835",
    }

    settings = {
        "weather": {
            "location": "83835",
            "label": "Hayden",
            "latitude": 47.7,
            "longitude": -116.7,
            "timezone": "America/Los_Angeles",
        }
    }
    with patch("festin.weather.urlopen", side_effect=URLError("down")):
        assert weather.weather_forecast(settings) == {
            "status": "unavailable",
            "location": "Hayden",
        }
        assert weather.weather_context(settings) == "Weather: temporarily unavailable."
    assert weather.weather_context({"weather": {"location": ""}}) == "Weather: not configured."
