"""Tattva plugin. Dinner hour lives here; sunrise cycles feed chat and the Log."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from festin import settings as core_settings
from festin.plugins.tattva import compute
from festin.weather import weather_forecast

PLUGIN_ID = "tattva"
PLUGIN_NAME = "Dinner tattva"


class TattvaPlugin:
    id = PLUGIN_ID
    name = PLUGIN_NAME

    def settings_schema(self) -> list[dict]:
        return [
            {
                "key": "dinnerHour",
                "type": "string",
                "default": compute.DEFAULT_DINNER_HOUR,
                "label": "Dinner hour",
                "help": (
                    "Each night's tattva is the element at this local time. "
                    "The hour exists for tattva; it is not a core setting."
                ),
                "input": "time",
            },
            {
                "key": "sideriodUrl",
                "type": "string",
                "default": "",
                "label": "Sideriod URL",
                "help": (
                    "Optional precise source (…/api/tattwa). Leave empty to compute "
                    "locally from sunrise at the weather location — no outside call."
                ),
            },
        ]

    def register(self, registry) -> None:
        registry.register_opening_contributor(_opening)

    def actions(self) -> dict:
        return {}

    def feed(self) -> dict:
        return {
            "elements": list(compute.ELEMENTS),
            "seeds": dict(compute.SEEDS),
            "note": compute.NOTE,
            "look": {name: compute.element_look(name) for name in compute.ELEMENTS},
        }

    def week_tattva(self, conn, week_start: str) -> dict[str, str] | None:
        hour, place, url = _params(conn)
        return compute.week_tint(week_start, hour, place, sideriod_url=url)


def _params(conn) -> tuple[str, dict | None, str]:
    from festin.plugins import host

    stored = host._stored(conn, PLUGIN)
    hour = compute.clean_dinner_hour(stored["settings"].get("dinnerHour"))
    url = str(stored["settings"].get("sideriodUrl") or "").strip()
    weather = core_settings.get_settings(conn).get("weather") or {}
    return hour, compute.place_from_weather(weather), url


def _opening(ctx: Any) -> str | None:
    conn = getattr(ctx, "conn", None)
    if conn is None:
        return None
    hour, place, url = _params(conn)
    settings = core_settings.get_settings(conn)
    forecast = weather_forecast(settings)
    if forecast.get("status") == "ok" and forecast.get("days"):
        days = [date.fromisoformat(str(day["date"])) for day in forecast["days"]]
    else:
        origin = core_settings.today(conn)
        days = [origin + timedelta(days=offset) for offset in range(5)]
    line = compute.context_line(days, hour, place, sideriod_url=url)
    season = compute.season_note(days[0] if days else None)
    return line + "\n" + season + "\n" + compute.NOTE


PLUGIN = TattvaPlugin()
