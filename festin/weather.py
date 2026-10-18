"""Open-Meteo geocode and forecast. Ported from live babette/server.py.

No HTTP routes here. Callers pass a settings dict with a nested weather object
(location, label, latitude, longitude, timezone). Forecast results cache for
three hours by (latitude, longitude).
"""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "Festin/1"
WEATHER_CACHE: dict[tuple[float, float], tuple[float, dict]] = {}


def resolve_weather_location(value):
    location = " ".join(str(value or "").split())
    if not location:
        return {"location": ""}
    if len(location) > 120:
        raise ValueError("Use a weather location under 120 characters.")
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
        {
            "name": location,
            "count": 1,
            "language": "en",
            "format": "json",
        }
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=8) as response:
            result = (json.load(response).get("results") or [])[0]
    except (HTTPError, URLError, TimeoutError, socket.timeout, ValueError, IndexError, KeyError, TypeError):
        raise ValueError(
            "That weather location could not be found. Try a city and state or postal code."
        ) from None
    label = ", ".join(
        str(part) for part in (result.get("name"), result.get("admin1"), result.get("country")) if part
    )
    return {
        "location": location,
        "label": label or location,
        "latitude": float(result["latitude"]),
        "longitude": float(result["longitude"]),
        "timezone": str(result.get("timezone") or "auto"),
    }


def weather_code(value):
    code = int(value)
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly cloudy"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "foggy"
    if code in (51, 53, 55, 56, 57):
        return "drizzly"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rainy"
    if code in (71, 73, 75, 77, 85, 86):
        return "snowy"
    if code in (95, 96, 99):
        return "stormy"
    return "mixed"


def weather_forecast(settings):
    configured = settings.get("weather") or {}
    if not configured.get("location"):
        return {"status": "not configured"}
    if "latitude" not in configured or "longitude" not in configured:
        return {"status": "unavailable", "location": configured.get("location")}
    cache_key = (configured["latitude"], configured["longitude"])
    cached = WEATHER_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < 3 * 60 * 60:
        return cached[1]
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
        {
            "latitude": configured["latitude"],
            "longitude": configured["longitude"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "forecast_days": 5,
            "timezone": configured.get("timezone") or "auto",
        }
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=8) as response:
            payload = json.load(response)
        daily = payload["daily"]
        days = [
            {
                "date": day,
                "conditions": weather_code(code),
                "low_f": round(low),
                "high_f": round(high),
                "rain_chance_pct": rain,
            }
            for day, code, low, high, rain in zip(
                daily["time"],
                daily["weather_code"],
                daily["temperature_2m_min"],
                daily["temperature_2m_max"],
                daily["precipitation_probability_max"],
            )
        ]
        result = {
            "status": "ok",
            "location": configured.get("label") or configured["location"],
            "days": days,
        }
        WEATHER_CACHE[cache_key] = (time.monotonic(), result)
        return result
    except (HTTPError, URLError, TimeoutError, socket.timeout, ValueError, KeyError, TypeError):
        return {
            "status": "unavailable",
            "location": configured.get("label") or configured["location"],
        }


def weather_context(settings):
    forecast = weather_forecast(settings)
    if forecast.get("status") == "not configured":
        return "Weather: not configured."
    if forecast.get("status") != "ok" or not forecast.get("days"):
        return "Weather: temporarily unavailable."
    parts = []
    for day in forecast["days"]:
        when = datetime.strptime(day["date"], "%Y-%m-%d")
        parts.append(
            f"{when:%a} {when.month}/{when.day} {day['high_f']}°/{day['low_f']}° {day['conditions']}"
        )
    return "Weather: " + " · ".join(parts)


def clear_cache() -> None:
    """Drop the in-process forecast cache. Tests use this between cases."""
    WEATHER_CACHE.clear()
