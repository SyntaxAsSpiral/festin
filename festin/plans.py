"""Dinner weeks by start date: read one week, save with expected_updated_at."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from festin import log as kitchen_log
from festin import settings as core_settings
from festin.errors import StaleState
from festin.schema import WEEKDAYS

_WEEKDAY_NUMBER = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def get_plan(conn: sqlite3.Connection, week_start: str) -> dict:
    start = _parse_week_start(week_start)
    week = conn.execute("SELECT * FROM weeks WHERE start_date = ?", (start.isoformat(),)).fetchone()
    if week is None:
        return _blank(start)
    return _public(conn, week)


def save_plan(conn: sqlite3.Connection, week_start: str, body: dict, *, now: datetime | None = None) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    start = _parse_week_start(week_start)
    if body.get("weekStart") not in (None, start.isoformat()):
        raise ValueError("weekStart must match the path.")
    existing = conn.execute("SELECT * FROM weeks WHERE start_date = ?", (start.isoformat(),)).fetchone()
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt", body.get("updatedAt")))
    if existing is not None and existing["updated_at"] != expected:
        raise StaleState(
            "This week was saved from another device. Open the week to load the latest dinners before saving."
        )
    days = body.get("days")
    if not isinstance(days, list) or len(days) != 7:
        raise ValueError("Use exactly seven dinners.")
    cleaned = []
    for index, slot in enumerate(days):
        if not isinstance(slot, dict):
            raise ValueError("Each night must be an object.")
        when = start + timedelta(days=index)
        day_name = _label_for(when)
        if "day" in slot and slot["day"] is not None:
            label = str(slot["day"]).strip().casefold()
            if label in _WEEKDAY_NUMBER and _WEEKDAY_NUMBER[label] != when.weekday():
                raise ValueError(f"{label} is not {when.isoformat()}")
            if label in WEEKDAYS:
                day_name = label
        recipe_id = slot.get("recipe")
        if recipe_id is not None:
            if not isinstance(recipe_id, str):
                raise ValueError("recipe must be text or null")
            recipe_id = recipe_id.strip() or None
        title = slot.get("title") if isinstance(slot.get("title"), str) else ""
        title = " ".join(title.split())
        ingredients = slot.get("ingredients") or []
        if not isinstance(ingredients, list) or any(not isinstance(item, str) for item in ingredients):
            raise ValueError("Dinner titles and ingredients must be text.")
        cleaned.append(
            {
                "day": day_name,
                "date": when.isoformat(),
                "recipe": recipe_id,
                "title": title,
                "ingredients": ingredients,
                "cooked": bool(slot.get("cooked")),
            }
        )
    slip_title = body.get("slipTitle", body.get("slipQuote"))
    if slip_title is None and existing is not None:
        slip_title = existing["slip_title"]
    elif slip_title is None:
        slip_title = ""
    if not isinstance(slip_title, str):
        raise ValueError("slipTitle must be text")
    slip_title = " ".join(slip_title.split())
    notes = body.get("notes")
    if notes is None and existing is not None:
        notes = existing["notes"]
    elif notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise ValueError("notes must be text")
    plates = body.get("plates", body.get("slipPlates"))
    if plates is None and existing is not None and existing["plates_json"]:
        plates_json = existing["plates_json"]
    elif plates is None:
        plates_json = None
    elif isinstance(plates, dict):
        plates_json = json.dumps(plates, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        raise ValueError("plates must be an object")
    stamp = _stamp(now)
    # Snapshot the forecast known now. Imported weeks leave weather_json empty.
    weather_json = None
    if existing is not None and existing["weather_json"]:
        weather_json = existing["weather_json"]
    snapped = kitchen_log.snapshot_weather(core_settings.get_settings(conn))
    if snapped:
        weather_json = snapped
    # Replace the week and its nights.
    dates = [start + timedelta(days=i) for i in range(7)]
    iso_dates = [d.isoformat() for d in dates]
    conn.executemany("DELETE FROM night_ingredients WHERE date = ?", [(d,) for d in iso_dates])
    conn.executemany("DELETE FROM nights WHERE date = ?", [(d,) for d in iso_dates])
    conn.execute("DELETE FROM weeks WHERE start_date = ?", (start.isoformat(),))
    conn.execute(
        """
        INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (start.isoformat(), slip_title, notes, plates_json, stamp, weather_json),
    )
    for slot in cleaned:
        conn.execute(
            """
            INSERT INTO nights (date, week_start, recipe_id, title, cooked, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                slot["date"],
                start.isoformat(),
                slot["recipe"],
                slot["title"],
                1 if slot["cooked"] else 0,
                stamp,
            ),
        )
        for position, item in enumerate(slot["ingredients"]):
            conn.execute(
                "INSERT INTO night_ingredients (date, position, text) VALUES (?, ?, ?)",
                (slot["date"], position, item),
            )
    conn.commit()
    return get_plan(conn, start.isoformat())


def _public(conn: sqlite3.Connection, week) -> dict:
    start = date.fromisoformat(week["start_date"])
    nights = conn.execute(
        "SELECT * FROM nights WHERE week_start = ? ORDER BY date",
        (week["start_date"],),
    ).fetchall()
    by_date = {row["date"]: row for row in nights}
    days = []
    for index in range(7):
        when = start + timedelta(days=index)
        iso = when.isoformat()
        row = by_date.get(iso)
        ingredients = [
            item["text"]
            for item in conn.execute(
                "SELECT text FROM night_ingredients WHERE date = ? ORDER BY position",
                (iso,),
            ).fetchall()
        ]
        if row is None:
            days.append(
                {
                    "day": _label_for(when),
                    "date": iso,
                    "recipe": None,
                    "title": "",
                    "ingredients": [],
                    "cooked": False,
                }
            )
        else:
            days.append(
                {
                    "day": _label_for(when),
                    "date": iso,
                    "recipe": row["recipe_id"],
                    "title": row["title"],
                    "ingredients": ingredients,
                    "cooked": bool(row["cooked"]),
                }
            )
    plates = json.loads(week["plates_json"]) if week["plates_json"] else None
    out = {
        "weekStart": week["start_date"],
        "slipTitle": week["slip_title"],
        "notes": week["notes"],
        "updatedAt": week["updated_at"],
        "days": days,
    }
    if plates is not None:
        out["plates"] = plates
    return out


def _blank(start: date) -> dict:
    return {
        "weekStart": start.isoformat(),
        "slipTitle": "",
        "notes": "",
        "updatedAt": None,
        "days": [
            {
                "day": _label_for(start + timedelta(days=index)),
                "date": (start + timedelta(days=index)).isoformat(),
                "recipe": None,
                "title": "",
                "ingredients": [],
                "cooked": False,
            }
            for index in range(7)
        ],
    }


def _parse_week_start(value) -> date:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("weekStart must be an ISO date.") from exc


def _label_for(when: date) -> str:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[when.weekday()]


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
