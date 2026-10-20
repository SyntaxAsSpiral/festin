"""Kitchen Log: timeline of weeks, recipe/note events, and chats.

GET /api/log?before= pages newest first. Week rows come from saved plans.
Recipe and note transitions are written into kitchen_log_events when they
happen through the API or Babette's tools; imported history is derived from
recipes, notes, and chats. Approximate imported chats fold into their week.

Weather on a week is the forecast snapshot stored when that plan was saved.
Imported weeks leave weather empty. Tattva is a hook only until a plugin lands.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from festin.settings import today as household_today, week_start_for, get_settings

PAGE_SIZE = 20
EVENT_KINDS = frozenset(
    {
        "recipe_added",
        "recipe_edited",
        "note_created",
        "recipe_cooked",
        "note_archived",
        "recipe_favourited",
        "photo_added",
        "recipe_planned",
    }
)


def record_event(
    conn: sqlite3.Connection,
    kind: str,
    *,
    ref_id: str,
    at: str,
    title: str = "",
    detail: str = "",
    extra: dict | None = None,
) -> None:
    """Append one recipe/note log line. Caller commits."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"Unknown kitchen log kind: {kind}")
    conn.execute(
        """
        INSERT INTO kitchen_log_events (kind, at, ref_id, title, detail, extra_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            kind,
            at,
            ref_id,
            title or "",
            detail or "",
            json.dumps(extra or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        ),
    )


def snapshot_weather(settings: dict) -> str | None:
    """Compact forecast JSON for a week row, or None when nothing useful is known."""
    from festin import weather as weather_mod

    forecast = weather_mod.weather_forecast(settings)
    if forecast.get("status") != "ok" or not forecast.get("days"):
        return None
    payload = {
        "location": forecast.get("location") or "",
        "days": forecast["days"],
        "summary": _weather_summary(forecast["days"]),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def week_tattva(conn: sqlite3.Connection, week_start: str):
    """Hook for the tattva plugin. Returns None while the plugin is off."""
    from festin.plugins import host
    from festin.plugins.tattva.plugin import PLUGIN_ID, PLUGIN

    if PLUGIN_ID not in host._BY_ID:
        return None
    if not host.enabled(conn, PLUGIN_ID):
        return None
    return PLUGIN.week_tattva(conn, week_start)


def list_log(
    conn: sqlite3.Connection,
    *,
    before: str | None = None,
    limit: int = PAGE_SIZE,
) -> dict:
    from festin import recipes as recipes_mod

    recipes_mod.close_ended_weeks(conn)
    limit = _page_limit(limit)
    cursor = _decode_before(before) if before else None
    entries = _collect(conn)
    _stamp_cook_ordinals(conn, entries)
    entries.sort(key=_sort_key, reverse=True)
    if cursor is not None:
        entries = [item for item in entries if _sort_key(item) < cursor]
    page = entries[:limit]
    next_cursor = None
    if len(entries) > limit:
        next_cursor = _encode_before(_sort_key(page[-1]))
    return {"entries": [_public(item) for item in page], "nextCursor": next_cursor}


# Words Babette may search a Log event by, beyond its title, ID and category.
EVENT_WORDS = {
    "recipe_added": "recipe added new",
    "recipe_edited": "recipe updated edited",
    "recipe_cooked": "recipe cooked made",
    "recipe_favourited": "recipe favourited favourite favorite loved",
    "photo_added": "recipe photo added picture",
    "recipe_planned": "recipe planned queued to-cook to cook",
    "note_created": "note created written",
    "note_archived": "note archived closed",
}


def search_events(
    conn: sqlite3.Connection,
    *,
    words: list[str] | None = None,
    days: int | None = None,
    limit: int = 12,
) -> list[dict]:
    """Recipe and note events, newest first, for Babette's history search.

    Weeks are left to the dinner history and chats to the message search.
    Every word must match; days keeps events within that many days of today.
    """
    since = None
    if days:
        since = (household_today(conn) - timedelta(days=days)).isoformat()
    from festin import recipes as recipes_mod

    recipes_mod.close_ended_weeks(conn)
    collected = _collect(conn)
    _stamp_cook_ordinals(conn, collected)
    found = []
    for item in collected:
        if item["kind"] not in EVENT_WORDS:
            continue
        if since and _as_at(item["at"])[:10] < since:
            continue
        if words:
            extra = item.get("extra") or {}
            text = " ".join(
                str(part or "")
                for part in (
                    item["title"], item["refId"], item["detail"],
                    extra.get("category"), extra.get("type"), EVENT_WORDS[item["kind"]],
                )
            ).casefold()
            if not all(word in text for word in words):
                continue
        found.append(item)
    found.sort(key=_sort_key, reverse=True)
    return [_public(item) for item in found[:limit]]


def _collect(conn: sqlite3.Connection) -> list[dict]:
    items: list[dict] = []
    items.extend(_week_entries(conn))
    items.extend(_event_entries(conn))
    items.extend(_derived_recipe_entries(conn))
    items.extend(_derived_note_entries(conn))
    items.extend(_chat_entries(conn))
    return items


def _current_week(conn: sqlite3.Connection) -> str:
    settings = get_settings(conn)
    return week_start_for(household_today(conn), settings["week_start_day"]).isoformat()


def _week_entries(conn: sqlite3.Connection) -> list[dict]:
    """Saved weeks that have ended. The week in progress gets no box: its events
    stay loose on the timeline, and the box is made once the week is over."""
    current_start = _current_week(conn)
    approx_by_week = _approx_chats_by_week(conn)
    rows = conn.execute("SELECT * FROM weeks ORDER BY start_date DESC").fetchall()
    items = []
    for week in rows:
        if week["start_date"] >= current_start:
            continue
        start = date.fromisoformat(week["start_date"])
        end = start + timedelta(days=6)
        nights = []
        for night in conn.execute(
            "SELECT date, title, recipe_id, cooked FROM nights WHERE week_start = ? ORDER BY date",
            (week["start_date"],),
        ).fetchall():
            nights.append(
                {
                    "date": night["date"],
                    "title": night["title"] or "",
                    "recipe": night["recipe_id"],
                    "cooked": bool(night["cooked"]),
                }
            )
        weather = None
        if week["weather_json"]:
            try:
                weather = json.loads(week["weather_json"])
            except (TypeError, json.JSONDecodeError):
                weather = None
        items.append(
            {
                "kind": "week",
                "id": week["start_date"],
                "at": _day_end(end),
                "weekStart": week["start_date"],
                "slipTitle": week["slip_title"] or "",
                "nights": nights,
                "conversations": approx_by_week.get(week["start_date"], []),
                "weather": weather,
                "tattva": week_tattva(conn, week["start_date"]),
                "updatedAt": week["updated_at"],
            }
        )
    return items


def _approx_chats_by_week(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Imported chats (date_approx=1) keyed by the plan weekStart they were dated to."""
    rows = conn.execute(
        """
        SELECT id, title, created_at, updated_at
        FROM chats
        WHERE created_at IS NOT NULL AND date_approx = 1
        ORDER BY created_at DESC, id
        """
    ).fetchall()
    by_week: dict[str, list[dict]] = {}
    for row in rows:
        week = str(row["created_at"] or "")[:10]
        if len(week) != 10:
            continue
        preview = ""
        first = conn.execute(
            """
            SELECT content FROM chat_messages
            WHERE chat_id = ? AND role = 'user' ORDER BY position LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        if first and isinstance(first["content"], str):
            preview = " ".join(first["content"].split())[:120]
        by_week.setdefault(week, []).append(
            {
                "id": row["id"],
                "title": row["title"] or preview or "Conversation",
                "at": _as_at(row["created_at"]),
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
        )
    return by_week

def _event_entries(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, kind, at, ref_id, title, detail, extra_json FROM kitchen_log_events"
    ).fetchall()
    items = []
    for row in rows:
        extra = json.loads(row["extra_json"] or "{}")
        items.append(
            {
                "kind": row["kind"],
                "id": f"event:{row['id']}",
                "at": row["at"],
                "refId": row["ref_id"],
                "title": row["title"] or "",
                "detail": row["detail"] or "",
                "extra": extra,
            }
        )
    return items


def _derived_recipe_entries(conn: sqlite3.Connection) -> list[dict]:
    """Import history: recipe created_at / updated_at when no matching API event exists."""
    recorded_adds = {
        row[0]
        for row in conn.execute(
            "SELECT ref_id FROM kitchen_log_events WHERE kind = 'recipe_added'"
        ).fetchall()
    }
    # Any recorded recipe event at that stamp covers the update (cooked/favourite/photo too).
    recorded_edits = {
        (row[0], row[1])
        for row in conn.execute(
            """
            SELECT ref_id, at FROM kitchen_log_events
            WHERE kind IN (
                'recipe_edited', 'recipe_cooked', 'recipe_favourited', 'photo_added',
                'recipe_planned'
            )
            """
        ).fetchall()
    }
    items = []
    for row in conn.execute(
        "SELECT id, title, category, created_at, updated_at FROM recipes"
    ).fetchall():
        created = row["created_at"]
        if created and row["id"] not in recorded_adds:
            items.append(
                {
                    "kind": "recipe_added",
                    "id": f"derived:recipe_added:{row['id']}",
                    "at": _as_at(created),
                    "refId": row["id"],
                    "title": row["title"] or "",
                    "detail": "",
                    "extra": {"category": row["category"]},
                }
            )
        updated = row["updated_at"]
        if (
            updated
            and created
            and updated != created
            and (row["id"], updated) not in recorded_edits
        ):
            items.append(
                {
                    "kind": "recipe_edited",
                    "id": f"derived:recipe_edited:{row['id']}:{updated}",
                    "at": _as_at(updated),
                    "refId": row["id"],
                    "title": row["title"] or "",
                    "detail": "",
                    "extra": {"category": row["category"]},
                }
            )
    return items


def _derived_note_entries(conn: sqlite3.Connection) -> list[dict]:
    recorded = {
        row[0]
        for row in conn.execute(
            "SELECT ref_id FROM kitchen_log_events WHERE kind = 'note_created'"
        ).fetchall()
    }
    items = []
    for row in conn.execute(
        """
        SELECT id, kind, text, written_on, updated_at FROM notes
        WHERE id NOT IN ('context-household', 'context-preferences', 'context-restrictions')
          AND kind NOT IN ('household', 'preferences', 'restrictions')
        """
    ).fetchall():
        if row["id"] in recorded:
            continue
        when = row["written_on"] or row["updated_at"]
        if not when:
            continue
        title = " ".join((row["text"] or "").split())
        if len(title) > 80:
            title = title[:79] + "…"
        items.append(
            {
                "kind": "note_created",
                "id": f"derived:note_created:{row['id']}",
                "at": _as_at(when),
                "refId": row["id"],
                "title": title,
                "detail": row["kind"] or "",
                "extra": {"type": row["kind"]},
            }
        )
    return items


def _chat_entries(conn: sqlite3.Connection) -> list[dict]:
    """Dated chats, and approximate imports from the week in progress. Older
    approximate imports ride inside their (ended) week's entry."""
    current_start = _current_week(conn)
    week_starts = {
        row[0]
        for row in conn.execute("SELECT start_date FROM weeks").fetchall()
        if row[0] < current_start
    }
    rows = conn.execute(
        """
        SELECT id, title, created_at, date_approx, updated_at
        FROM chats
        WHERE created_at IS NOT NULL
          AND EXISTS (SELECT 1 FROM chat_messages WHERE chat_id = chats.id)
        """
    ).fetchall()
    items = []
    for row in rows:
        if row["date_approx"]:
            week = str(row["created_at"] or "")[:10]
            if week in week_starts:
                continue
        preview = ""
        first = conn.execute(
            """
            SELECT content FROM chat_messages
            WHERE chat_id = ? AND role = 'user' ORDER BY position LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        if first and isinstance(first["content"], str):
            preview = " ".join(first["content"].split())[:120]
        items.append(
            {
                "kind": "chat",
                "id": row["id"],
                "at": _as_at(row["created_at"]),
                "refId": row["id"],
                "title": row["title"] or preview or "Conversation",
                "detail": preview,
                "dateApprox": bool(row["date_approx"]),
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
        )
    return items


def _public(item: dict) -> dict:
    kind = item["kind"]
    if kind == "week":
        out = {
            "kind": "week",
            "at": item["at"],
            "weekStart": item["weekStart"],
            "slipTitle": item["slipTitle"],
            "nights": item["nights"],
            "conversations": item.get("conversations") or [],
            "weather": item["weather"],
            "tattva": item["tattva"],
            "updatedAt": item["updatedAt"],
        }
        return out
    if kind == "chat":
        return {
            "kind": "chat",
            "at": item["at"],
            "id": item["id"],
            "title": item["title"],
            "dateApprox": item["dateApprox"],
            "createdAt": item["createdAt"],
            "updatedAt": item["updatedAt"],
        }
    out = {
        "kind": kind,
        "at": item["at"],
        "id": item["refId"],
        "title": item["title"],
        "detail": item["detail"],
    }
    extra = item.get("extra") or {}
    if "category" in extra and extra["category"] is not None:
        out["category"] = extra["category"]
    if kind in ("note_created", "note_archived") and extra.get("type"):
        out["type"] = extra["type"]
    if kind == "recipe_cooked" and extra.get("date"):
        out["date"] = extra["date"]
    if kind == "recipe_cooked" and item.get("ordinal"):
        out["ordinal"] = item["ordinal"]
    return out


def _stamp_cook_ordinals(conn: sqlite3.Connection, entries: list[dict]) -> None:
    """Ordinal of each recipe_cooked event in the recipe's unified cook-date set."""
    from festin import recipes as recipes_mod

    cooks = [item for item in entries if item.get("kind") == "recipe_cooked"]
    if not cooks:
        return
    ids = list({item.get("refId") for item in cooks if item.get("refId")})
    dates_by = recipes_mod.cook_dates_for(conn, ids)
    for item in cooks:
        ref = item.get("refId") or ""
        day = _event_cook_date(item)
        dates = list(dates_by.get(ref) or [])
        if day and day not in dates:
            dates = sorted(set(dates) | {day})
        if day and day in dates:
            item["ordinal"] = dates.index(day) + 1
        else:
            item["ordinal"] = 1


def _event_cook_date(item: dict) -> str | None:
    extra = item.get("extra") or {}
    for candidate in (extra.get("date"), item.get("detail"), item.get("at")):
        text = str(candidate or "").strip()
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
    return None


def _sort_key(item: dict) -> tuple:
    return (_as_at(item["at"]), item["kind"], item["id"])


def _as_at(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "0000-00-00T00:00:00.000000Z"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text + "T12:00:00.000000Z"
    return text


def _day_end(when: date) -> str:
    return when.isoformat() + "T23:59:59.000000Z"


def _weather_summary(days: list[dict]) -> str:
    if not days:
        return ""
    highs = [day.get("high_f") for day in days if day.get("high_f") is not None]
    conditions = [day.get("conditions") for day in days if day.get("conditions")]
    parts = []
    if highs:
        parts.append(f"{max(highs)}°")
    if conditions:
        counts: dict[str, int] = {}
        order: list[str] = []
        for label in conditions:
            if label not in counts:
                order.append(label)
            counts[label] = counts.get(label, 0) + 1
        best = max(order, key=lambda label: (counts[label], -order.index(label)))
        parts.append(best)
    return " ".join(parts)


def _page_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return PAGE_SIZE
    return min(limit, 100)


def _encode_before(key: tuple) -> str:
    return base64.urlsafe_b64encode(json.dumps(list(key)).encode()).decode().rstrip("=")


def _decode_before(cursor: str) -> tuple:
    pad = "=" * (-len(cursor) % 4)
    try:
        parts = json.loads(base64.urlsafe_b64decode(cursor + pad))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Bad before cursor") from exc
    if not isinstance(parts, list) or len(parts) != 3:
        raise ValueError("Bad before cursor")
    at, kind, item_id = parts
    if not isinstance(at, str) or not isinstance(kind, str) or not isinstance(item_id, str):
        raise ValueError("Bad before cursor")
    return (at, kind, item_id)
