"""Shared core settings: table name, weather location, dinner hour, week start.

'today' and week bounds use the stored weather timezone. With no location yet,
or with 'auto' / an unknown zone, they fall back to the server's local zone.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from festin.schema import WEEKDAYS
from festin.weather import resolve_weather_location

DEFAULT_TABLE_NAME = "Babette's Table"
DEFAULT_DINNER_HOUR = "17:30"
DEFAULT_WEEK_START = "sat"

# Python weekday numbers match the importer.
_WEEKDAY_NUMBER = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def get_settings(conn: sqlite3.Connection) -> dict:
    """Return the single settings row, with weather nested as live expects."""
    row = conn.execute(
        """
        SELECT table_name, week_start_day, dinner_hour, updated_at,
               weather_location, weather_label, weather_latitude,
               weather_longitude, weather_timezone
        FROM settings WHERE id = 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("settings row is missing")
    weather: dict = {"location": row["weather_location"] or ""}
    if row["weather_location"]:
        weather["label"] = row["weather_label"] or row["weather_location"]
        if row["weather_latitude"] is not None:
            weather["latitude"] = row["weather_latitude"]
        if row["weather_longitude"] is not None:
            weather["longitude"] = row["weather_longitude"]
        if row["weather_timezone"]:
            weather["timezone"] = row["weather_timezone"]
    return {
        "table_name": row["table_name"],
        "week_start_day": row["week_start_day"],
        "dinner_hour": row["dinner_hour"],
        "updated_at": row["updated_at"],
        "weather": weather,
    }


def update_settings(
    conn: sqlite3.Connection,
    *,
    table_name: str | None = None,
    week_start_day: str | None = None,
    dinner_hour: str | None = None,
    weather_location: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Write core fields. Geocode when the weather location string changes."""
    current = get_settings(conn)
    next_table = current["table_name"] if table_name is None else _clean_table_name(table_name)
    next_week = (
        current["week_start_day"] if week_start_day is None else _clean_week_start(week_start_day)
    )
    next_dinner = (
        current["dinner_hour"] if dinner_hour is None else _clean_dinner_hour(dinner_hour)
    )

    weather = dict(current["weather"])
    if weather_location is not None:
        requested = " ".join(str(weather_location).split())
        if requested != weather.get("location"):
            weather = resolve_weather_location(requested)

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn.execute(
        """
        UPDATE settings SET
            table_name = ?,
            week_start_day = ?,
            dinner_hour = ?,
            weather_location = ?,
            weather_label = ?,
            weather_latitude = ?,
            weather_longitude = ?,
            weather_timezone = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (
            next_table,
            next_week,
            next_dinner,
            weather.get("location") or "",
            weather.get("label") or "",
            weather.get("latitude"),
            weather.get("longitude"),
            weather.get("timezone") or "",
            stamp,
        ),
    )
    conn.commit()
    return get_settings(conn)


def today(conn: sqlite3.Connection, *, now: datetime | None = None) -> date:
    """Calendar date in the household timezone for the given UTC instant."""
    return _local_instant(conn, now).date()


def week_bounds(
    conn: sqlite3.Connection,
    *,
    on: date | None = None,
    now: datetime | None = None,
) -> tuple[date, date]:
    """Inclusive start and inclusive end of the kitchen week that contains `on`.

    `on` defaults to today() in the stored timezone. The start day comes from
    settings.week_start_day.
    """
    settings = get_settings(conn)
    day = on if on is not None else today(conn, now=now)
    start = week_start_for(day, settings["week_start_day"])
    end = start + timedelta(days=6)
    return start, end


def week_start_for(day: date, start_day: str) -> date:
    """Most recent occurrence of start_day on or before day."""
    target = _WEEKDAY_NUMBER[_clean_week_start(start_day)]
    return day - timedelta(days=(day.weekday() - target) % 7)


def _local_instant(conn: sqlite3.Connection, now: datetime | None) -> datetime:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    zone_name = (get_settings(conn).get("weather") or {}).get("timezone") or ""
    if not zone_name or zone_name == "auto":
        return instant.astimezone()
    try:
        return instant.astimezone(ZoneInfo(zone_name))
    except ZoneInfoNotFoundError:
        return instant.astimezone()


def _clean_table_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 80:
        raise ValueError("Enter a table name under 80 characters.")
    return name


def _clean_week_start(value) -> str:
    day = str(value or "").strip().lower()
    if day not in WEEKDAYS:
        raise ValueError("Week start must be one of sat, sun, mon, tue, wed, thu, fri.")
    return day


def _clean_dinner_hour(value) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_DINNER_HOUR
    parts = text.split(":")
    if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
        raise ValueError("Use a dinner hour like 17:30.")
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59 or (len(parts) == 3 and int(parts[2]) > 59):
        raise ValueError("Use a dinner hour like 17:30.")
    return f"{hour:02d}:{minute:02d}"
