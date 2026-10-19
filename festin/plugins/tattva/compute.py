"""Local dinner-hour tattva from sunrise, with an optional sideriod override.

24-minute cycles of Prithvi → Apas → Tejas → Vayu → Akasha, anchored at the
day's sunrise (NOAA approximation). Weekday DAY_START is the fallback when
lat/lon is missing or a cycle cannot be computed. An optional sideriod URL
may supply a more precise cycle; failures fall back to local compute.
"""

from __future__ import annotations

import json
import math
import socket
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DINNER_HOUR = "17:30"
CYCLE = timedelta(minutes=24)
TURN_WINDOW = timedelta(minutes=30)
ELEMENTS = ("Akasha", "Vayu", "Tejas", "Prithvi", "Apas")
STANDARD_SEQUENCE = ["Prithvi", "Apas", "Tejas", "Vayu", "Akasha"]

# Python weekday(): Mon=0 ... Sun=6. Matches sideriod TATTWA_START / live DAY_START.
DAY_START = {
    0: "Apas",  # Monday
    1: "Tejas",  # Tuesday
    2: "Prithvi",  # Wednesday
    3: "Akasha",  # Thursday
    4: "Apas",  # Friday
    5: "Vayu",  # Saturday
    6: "Tejas",  # Sunday
}

SEEDS = {
    "Akasha": "ether — space, light, simple; do not pile another heavy stew",
    "Vayu": "air — mobile, dry; ground with oil, grain, broth",
    "Tejas": "fire — sharp, cooked, pungent; one fire night, not three",
    "Prithvi": "earth — dense, nourishing; beans, roast, root, pastry",
    "Apas": "water — moist, cooling, sour-sweet; soup, cabbage, salad as companion",
}

# Glyph + Log accent (mock Frappé washed 30% to sepia).
ELEMENT_LOOK = {
    "Tejas": {"glyph": "🜂", "colour": "#ba6d66"},
    "Prithvi": {"glyph": "🜃", "colour": "#ac8c54"},
    "Vayu": {"glyph": "🜁", "colour": "#7a88b0"},
    "Akasha": {"glyph": "⊙", "colour": "#a580aa"},
    "Apas": {"glyph": "🜄", "colour": "#938cae"},
}

NOTE = (
    "Dinner tattva is the element at the household dinner hour. "
    "When the next cycle starts within 30 minutes, the line names that turn. "
    "Without a weather location, or when sunrise cannot be computed, the weekday "
    "day-start table is the labeled fallback. Honor operator requests first. Then "
    "vary elements: do not run Tejas three nights running; after Prithvi (roast, "
    "beans, pie) the next night may be lighter or leftover."
)

_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str, str], dict[str, dict[str, str]]] = {}

# Injectable for tests. Signature matches urllib.request.urlopen.
_urlopen: Callable = urlopen
SIDERIOD_TIMEOUT = 2


def clean_dinner_hour(value) -> str:
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


def season_note(when: Optional[date] = None) -> str:
    when = when or date.today()
    month = when.month
    if month in (9, 10, 11):
        return (
            "Early autumn / Vata rising. Favor warm, moist, grounding "
            "(prithvi, apas, a little tejas). Do not stack dry, raw, or fiery nights."
        )
    if month in (12, 1, 2):
        return (
            "Winter. Build agni with warm, oily, cooked food. Prithvi and tejas. "
            "Raw salad is a companion, not the supper."
        )
    if month in (3, 4, 5):
        return (
            "Spring. Lighter, more bitter/astringent, still cooked. "
            "Do not bury the table in cream every night."
        )
    return "Summer / Pitta. Cooler, less pungent. Apas and prithvi. Tejas once, not all week."


def place_from_weather(weather: Optional[dict]) -> Optional[dict]:
    """lat/lon/tz from core weather settings, or None when incomplete."""
    if not isinstance(weather, dict):
        return None
    lat = weather.get("latitude")
    lon = weather.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        place = {"lat": float(lat), "lon": float(lon)}
    except (TypeError, ValueError):
        return None
    zone = weather.get("timezone")
    if isinstance(zone, str) and zone.strip() and zone.strip() != "auto":
        place["tz"] = zone.strip()
    return place


def element_look(name: str) -> dict[str, str]:
    row = ELEMENT_LOOK.get(name) or ELEMENT_LOOK["Akasha"]
    return {"name": name, "glyph": row["glyph"], "colour": row["colour"]}


def noaa_sun_event(
    day: date, lat: float, lon: float, tz: ZoneInfo, event: str
) -> Optional[datetime]:
    """Approximate sunrise/sunset (NOAA). Returns localized datetime or None at poles."""
    if event not in {"rise", "set"}:
        raise ValueError("event must be rise or set")
    zenith = 90.833
    n = day.timetuple().tm_yday
    lng_hour = lon / 15.0
    t = n + ((6 - lng_hour) / 24.0 if event == "rise" else (18 - lng_hour) / 24.0)
    mean_anomaly = (0.9856 * t) - 3.289
    true_long = (
        mean_anomaly
        + (1.916 * math.sin(math.radians(mean_anomaly)))
        + (0.020 * math.sin(math.radians(2 * mean_anomaly)))
        + 282.634
    )
    true_long = true_long % 360.0
    right_asc = math.degrees(math.atan(0.91764 * math.tan(math.radians(true_long))))
    right_asc = right_asc % 360.0
    l_quadrant = math.floor(true_long / 90.0) * 90.0
    ra_quadrant = math.floor(right_asc / 90.0) * 90.0
    right_asc = (right_asc + (l_quadrant - ra_quadrant)) / 15.0
    sin_dec = 0.39782 * math.sin(math.radians(true_long))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (
        math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(lat)))
    ) / (cos_dec * math.cos(math.radians(lat)))
    if cos_h > 1 or cos_h < -1:
        return None
    hour_angle = (
        360.0 - math.degrees(math.acos(cos_h)) if event == "rise" else math.degrees(math.acos(cos_h))
    )
    hour_angle /= 15.0
    local_mean = hour_angle + right_asc - (0.06571 * t) - 6.622
    utc_hour = (local_mean - lng_hour) % 24.0
    hour = int(utc_hour)
    minute_float = (utc_hour - hour) * 60
    minute = int(minute_float)
    second = int(round((minute_float - minute) * 60))
    if second == 60:
        second = 0
        minute += 1
    if minute == 60:
        minute = 0
        hour = (hour + 1) % 24
    utc_dt = datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=timezone.utc)
    return utc_dt.astimezone(tz)


def local_tattwa(now: datetime, lat: float, lon: float, tz: ZoneInfo) -> dict[str, Any]:
    """Element and segment bounds at `now` from the most recent sunrise."""
    sunrise = noaa_sun_event(now.date(), lat, lon, tz, "rise")
    if sunrise is None:
        raise ValueError("sunrise unavailable")
    source_day = now.date()
    if now < sunrise:
        source_day = now.date() - timedelta(days=1)
        sunrise = noaa_sun_event(source_day, lat, lon, tz, "rise")
        if sunrise is None:
            raise ValueError("sunrise unavailable")
    minutes = (now - sunrise).total_seconds() / 60.0
    cycle_pos = minutes % 120.0
    segment_index = int(cycle_pos // 24)
    start_element = DAY_START[source_day.weekday()]
    start_index = STANDARD_SEQUENCE.index(start_element)
    element = STANDARD_SEQUENCE[(start_index + segment_index) % len(STANDARD_SEQUENCE)]
    segment_start = now - timedelta(minutes=(cycle_pos % 24))
    segment_end = segment_start + CYCLE
    return {
        "element": element,
        "start_element": start_element,
        "segment_minutes": 24,
        "segment_starts_at": segment_start,
        "segment_ends_at": segment_end,
        "source_sunrise": sunrise,
    }


def _zone_for(place: Optional[dict]) -> ZoneInfo:
    name = (place or {}).get("tz") if place else None
    if isinstance(name, str) and name.strip():
        try:
            return ZoneInfo(name.strip())
        except ZoneInfoNotFoundError:
            pass
    local = datetime.now().astimezone()
    key = getattr(local.tzinfo, "key", None)
    if isinstance(key, str) and key:
        try:
            return ZoneInfo(key)
        except ZoneInfoNotFoundError:
            pass
    return ZoneInfo("UTC")


def _clock(day: date, hour: str, tz: ZoneInfo) -> datetime:
    hh, mm = (int(part) for part in hour.split(":"))
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)


def _fallback(day: date) -> dict[str, str]:
    name = DAY_START[day.weekday()]
    return {
        "date": day.isoformat(),
        "phrase": name,
        "element": name,
        "source": "weekday fallback",
    }


def _phrase(dinner: datetime, element: str, ends_at: datetime, next_element: str) -> tuple[str, str]:
    if element not in ELEMENTS:
        raise ValueError("bad element")
    delta = ends_at - dinner
    if timedelta(0) < delta <= TURN_WINDOW and next_element in ELEMENTS:
        clock = f"{ends_at.hour:02d}:{ends_at.minute:02d}"
        return f"{element}, turning {next_element} at {clock}", element
    return element, element


def _local_night(day: date, hour: str, place: dict) -> dict[str, str]:
    tz = _zone_for(place)
    dinner = _clock(day, hour, tz)
    try:
        current = local_tattwa(dinner, place["lat"], place["lon"], tz)
        nxt = local_tattwa(current["segment_ends_at"], place["lat"], place["lon"], tz)
        phrase, element = _phrase(
            dinner,
            current["element"],
            current["segment_ends_at"],
            nxt["element"],
        )
    except (ValueError, KeyError, TypeError, OverflowError):
        return _fallback(day)
    return {
        "date": day.isoformat(),
        "phrase": phrase,
        "element": element,
        "source": "local",
    }


def _naive(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _sideriod_fetch(
    days: list[date], hour: str, place: Optional[dict], base_url: str
) -> dict[str, dict[str, str]]:
    tz = _zone_for(place)
    pairs = []
    instants = []
    for day in days:
        dinner = _clock(day, hour, tz)
        later = dinner + CYCLE
        pairs.append((day, dinner, later))
        # sideriod accepts naive or offset; send local wall time without offset, matching live.
        instants.append(dinner.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"))
        instants.append(later.replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"))
    query: dict[str, Any] = {"at": ",".join(instants)}
    if place is not None:
        query["lat"] = place["lat"]
        query["lon"] = place["lon"]
        if place.get("tz"):
            query["tz"] = place["tz"]
    url = base_url.rstrip("/")
    if not url.endswith("/api/tattwa"):
        url = url + "/api/tattwa"
    request = Request(url + "?" + urlencode(query), headers={"User-Agent": "Festin/tattva"})
    with _urlopen(request, timeout=SIDERIOD_TIMEOUT) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("sideriod tattwa")
    by_clock = {}
    for row in payload["results"]:
        if isinstance(row, dict) and row.get("at"):
            by_clock[_naive(str(row["at"]))] = row
    found = {}
    for day, dinner, later in pairs:
        current = by_clock.get(dinner.replace(tzinfo=None).replace(microsecond=0))
        if not current:
            found[day.isoformat()] = _fallback(day)
            continue
        try:
            name = str(current.get("name") or "")
            ends = _naive(str(current["ends_at"]))
            nxt = by_clock.get(later.replace(tzinfo=None).replace(microsecond=0))
            turn = str((nxt or {}).get("name") or "")
            phrase, element = _phrase(dinner.replace(tzinfo=None), name, ends, turn)
        except (ValueError, KeyError, TypeError):
            found[day.isoformat()] = _fallback(day)
            continue
        found[day.isoformat()] = {
            "date": day.isoformat(),
            "phrase": phrase,
            "element": element,
            "source": "sideriod",
        }
    return found


def dinner_nights(
    days: list[date],
    dinner_hour: str = DEFAULT_DINNER_HOUR,
    place: Optional[dict] = None,
    *,
    sideriod_url: str = "",
) -> list[dict[str, str]]:
    """Tattva at the dinner hour for each date."""
    hour = clean_dinner_hour(dinner_hour)
    today = date.today().isoformat()
    url = (sideriod_url or "").strip()
    if place and place.get("lat") is not None and place.get("lon") is not None:
        place_key = f"{place['lat']}:{place['lon']}:{place.get('tz') or ''}"
    else:
        place_key = "none"
    source_key = url or ("local" if place_key != "none" else "weekday")
    key = (today, hour, source_key, place_key)
    with _LOCK:
        stale = [item for item in _CACHE if item[0] != today]
        for item in stale:
            _CACHE.pop(item, None)
        have = dict(_CACHE.get(key, {}))
    missing = [day for day in days if day.isoformat() not in have]
    if missing:
        fetched: dict[str, dict[str, str]] = {}
        url = (sideriod_url or "").strip()
        if url:
            try:
                fetched = _sideriod_fetch(missing, hour, place, url)
            except (
                HTTPError,
                URLError,
                TimeoutError,
                socket.timeout,
                json.JSONDecodeError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
            ):
                fetched = {}
        if not fetched:
            if place and place.get("lat") is not None and place.get("lon") is not None:
                fetched = {day.isoformat(): _local_night(day, hour, place) for day in missing}
            else:
                fetched = {day.isoformat(): _fallback(day) for day in missing}
        live = {
            iso: row
            for iso, row in fetched.items()
            if row["source"] in ("sideriod", "local")
        }
        if live:
            with _LOCK:
                _CACHE.setdefault(key, {}).update(live)
        have.update(fetched)
    return [have[day.isoformat()] for day in days]


def context_line(
    days: list[date],
    dinner_hour: str = DEFAULT_DINNER_HOUR,
    place: Optional[dict] = None,
    *,
    sideriod_url: str = "",
) -> str:
    rows = dinner_nights(days, dinner_hour, place, sideriod_url=sideriod_url)
    precise = {"sideriod", "local"}
    all_fallback = all(row["source"] not in precise for row in rows) if rows else True
    parts = []
    for row in rows:
        when = date.fromisoformat(row["date"])
        phrase = row["phrase"]
        if row["source"] not in precise and not all_fallback:
            phrase += " (weekday fallback)"
        parts.append(f"{when:%a} {when.month}/{when.day} {phrase}")
    label = "Dinner tattva (weekday fallback)" if all_fallback else "Dinner tattva"
    return label + ": " + " · ".join(parts)


def week_tint(
    week_start: str,
    dinner_hour: str = DEFAULT_DINNER_HOUR,
    place: Optional[dict] = None,
    *,
    sideriod_url: str = "",
) -> dict[str, str]:
    """Log accent for a kitchen week: element at dinner on the week-start night."""
    start = date.fromisoformat(week_start)
    row = dinner_nights([start], dinner_hour, place, sideriod_url=sideriod_url)[0]
    look = element_look(row["element"])
    look["source"] = row["source"]
    look["phrase"] = row["phrase"]
    return look


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()
