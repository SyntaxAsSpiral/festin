"""Shared recipe catalog: list, read, create, edit, delete, photos, mark cooked."""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from festin import log as kitchen_log
from festin.errors import NotFound, StaleState
from festin.settings import get_settings, today as household_today, week_start_for

PAGE_SIZE = 20
RECIPE_ID = re.compile(r"^CBK-(\d+)$")

# Writable fields on create/edit (API camelCase → column).
_STRING_FIELDS = {
    "title": "title",
    "kind": "kind",
    "category": "category",
    "voice": "voice",
    "source": "source",
    "provenance": "provenance",
    "status": "status",
    "searchDescription": "search_description",
    "method": "method",
    "notes": "notes",
    "context": "context",
    "ocrText": "ocr_text",
}
_BOOL_FIELDS = {
    "stub": "stub",
    "needsPracticeReview": "needs_practice_review",
    "favourite": "favourite",
}
_LIST_FIELDS = {
    "ingredients": "ingredients_json",
    "appliesTo": "applies_to_json",
    "tattva": "tattva_json",
}
# `queued` is a bool toggle; storage is recipes.queued_at (ISO stamp or NULL).

# Stored forms. Input may still say "recipe" for one release; that means formule.
_FORM_KINDS = frozenset(("formule", "praxis"))


def _normalize_kind(value) -> str:
    if value in (None, ""):
        return "formule"
    if not isinstance(value, str):
        raise ValueError("Invalid recipe field: kind")
    kind = value.strip().casefold()
    if kind == "recipe":
        return "formule"
    if kind not in _FORM_KINDS:
        raise ValueError("Invalid recipe field: kind")
    return kind


def list_recipes(
    conn: sqlite3.Connection,
    *,
    q: str = "",
    cursor: str | None = None,
    limit: int = PAGE_SIZE,
    sample: bool = False,
    categories: list[str] | None = None,
    queued: bool = False,
) -> dict:
    close_ended_weeks(conn)
    limit = _page_limit(limit)
    if sample:
        # Queued first (oldest first), then a random handful for the Meals frieze.
        # Optional categories: 'misc' also takes recipes with no category.
        return {
            "recipes": [_card(item) for item in _sample_with_queue(conn, limit, categories)],
            "nextCursor": None,
        }
    params: list = []
    where = []
    if queued:
        where.append("queued_at IS NOT NULL")
    if q:
        needle = f"%{' '.join(q.split()).casefold()}%"
        where.append(
            """(
                lower(title) LIKE ? OR lower(id) LIKE ? OR lower(ifnull(category, '')) LIKE ?
                OR lower(search_description) LIKE ? OR lower(notes) LIKE ?
            )"""
        )
        params.extend([needle, needle, needle, needle, needle])
    if cursor:
        if queued:
            stamp, recipe_id = _decode_queue_cursor(cursor)
            where.append("((queued_at > ?) OR (queued_at = ? AND id > ?))")
            params.extend([stamp, stamp, recipe_id])
        else:
            title, recipe_id = _decode_cursor(cursor)
            where.append("((title > ?) OR (title = ? AND id > ?))")
            params.extend([title, title, recipe_id])
    sql = "SELECT * FROM recipes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if queued:
        sql += " ORDER BY queued_at ASC, id ASC LIMIT ?"
    else:
        sql += " ORDER BY title COLLATE NOCASE, id LIMIT ?"
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()
    items = attach_cook_stats_many(conn, [_public(row) for row in rows[:limit]])
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        if queued:
            next_cursor = _encode_queue_cursor(last["queued_at"], last["id"])
        else:
            next_cursor = _encode_cursor(last["title"], last["id"])
    return {"recipes": [_card(item) for item in items], "nextCursor": next_cursor}


def queued_titles(conn: sqlite3.Connection, *, limit: int = 12) -> list[dict]:
    """Short queue for Babette's planning context: oldest first."""
    rows = conn.execute(
        """
        SELECT id, title FROM recipes
        WHERE queued_at IS NOT NULL
        ORDER BY queued_at ASC, id ASC
        LIMIT ?
        """,
        (max(1, min(limit, 40)),),
    ).fetchall()
    return [{"id": row["id"], "title": row["title"]} for row in rows]


def get_recipe(conn: sqlite3.Connection, recipe_id: str) -> dict:
    close_ended_weeks(conn)
    row = _row(conn, recipe_id)
    return attach_cook_stats(conn, _public(row))


def cook_dates_for(conn: sqlite3.Connection, recipe_ids: list[str] | None = None) -> dict[str, list[str]]:
    """Distinct cook dates per recipe: recipe_cooked events ∪ linked nights in ended weeks.

    A cook is a distinct (recipe, date). An event dated the same day as a linked
    ended-week night is one cook. Ended-week nights write no Log lines; they only
    feed this set (and close_ended_weeks for the queue). Dates are ISO YYYY-MM-DD,
    sorted ascending per recipe.
    """
    settings = get_settings(conn)
    current_start = week_start_for(household_today(conn), settings["week_start_day"]).isoformat()
    by_recipe: dict[str, set[str]] = {}

    event_sql = """
        SELECT ref_id AS id,
               COALESCE(
                 json_extract(extra_json, '$.date'),
                 CASE WHEN length(detail) >= 10 THEN substr(detail, 1, 10) END,
                 substr(at, 1, 10)
               ) AS cook_date
        FROM kitchen_log_events
        WHERE kind = 'recipe_cooked'
        """
    event_args: list = []
    if recipe_ids is not None:
        if not recipe_ids:
            return {}
        marks = ",".join("?" * len(recipe_ids))
        event_sql += f" AND ref_id IN ({marks})"
        event_args.extend(recipe_ids)
    for row in conn.execute(event_sql, event_args).fetchall():
        day = _as_iso_date(row["cook_date"])
        if row["id"] and day:
            by_recipe.setdefault(row["id"], set()).add(day)

    night_sql = """
        SELECT recipe_id AS id, date AS cook_date
        FROM nights
        WHERE recipe_id IS NOT NULL AND recipe_id != '' AND week_start < ?
        """
    night_args: list = [current_start]
    if recipe_ids is not None:
        marks = ",".join("?" * len(recipe_ids))
        night_sql += f" AND recipe_id IN ({marks})"
        night_args.extend(recipe_ids)
    for row in conn.execute(night_sql, night_args).fetchall():
        day = _as_iso_date(row["cook_date"])
        if row["id"] and day:
            by_recipe.setdefault(row["id"], set()).add(day)

    return {rid: sorted(days) for rid, days in by_recipe.items()}


def cook_stats_for(conn: sqlite3.Connection, recipe_ids: list[str]) -> dict[str, dict]:
    """Derived cookCount and lastCooked from cook_dates_for."""
    dates = cook_dates_for(conn, recipe_ids)
    return {
        rid: {"cookCount": len(days), "lastCooked": days[-1] if days else None}
        for rid, days in dates.items()
    }


def close_ended_weeks(conn: sqlite3.Connection) -> int:
    """Clear queued_at when a recipe was linked on an ended-week night after it was queued.

    A recipe queued again after that dinner keeps its mark (queued_at on or after
    the night's date). Idempotent. Writes no Log events. Commits when it clears
    anything. Call from recipe/log/plan read paths.
    """
    settings = get_settings(conn)
    current_start = week_start_for(household_today(conn), settings["week_start_day"]).isoformat()
    rows = conn.execute(
        """
        SELECT r.id AS id, r.queued_at AS queued_at, n.date AS night_date
        FROM recipes r
        JOIN nights n ON n.recipe_id = r.id
        WHERE r.queued_at IS NOT NULL
          AND n.week_start < ?
          AND n.recipe_id IS NOT NULL
          AND n.recipe_id != ''
        """,
        (current_start,),
    ).fetchall()
    to_clear: set[str] = set()
    for row in rows:
        queued = str(row["queued_at"] or "")
        night = _as_iso_date(row["night_date"])
        if not queued or not night:
            continue
        if queued[:10] < night:
            to_clear.add(row["id"])
    if not to_clear:
        return 0
    stamp = _stamp(None)
    conn.executemany(
        "UPDATE recipes SET queued_at = NULL, updated_at = ? WHERE id = ? AND queued_at IS NOT NULL",
        [(stamp, rid) for rid in to_clear],
    )
    conn.commit()
    return len(to_clear)


def _as_iso_date(value) -> str | None:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def attach_cook_stats(conn: sqlite3.Connection, recipe: dict) -> dict:
    stats = cook_stats_for(conn, [recipe["id"]]).get(recipe["id"], {})
    recipe["cookCount"] = stats.get("cookCount", 0)
    recipe["lastCooked"] = stats.get("lastCooked")
    return recipe


def attach_cook_stats_many(conn: sqlite3.Connection, recipes: list[dict]) -> list[dict]:
    stats = cook_stats_for(conn, [r["id"] for r in recipes if r.get("id")])
    for recipe in recipes:
        s = stats.get(recipe.get("id"), {})
        recipe["cookCount"] = s.get("cookCount", 0)
        recipe["lastCooked"] = s.get("lastCooked")
    return recipes


def create_recipe(
    conn: sqlite3.Connection,
    body: dict,
    *,
    now: datetime | None = None,
    log_detail: str = "",
) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    stamp = _stamp(now)
    fields = _parse_fields(body, creating=True, stamp=stamp)
    if not fields.get("title"):
        raise ValueError("Cookbook cards require a title.")
    kind = fields.get("kind") or "formule"
    if kind == "praxis":
        if not (fields.get("method") or "").strip():
            raise ValueError("Praxis cards require a method.")
        if "applies_to_json" not in fields:
            fields["applies_to_json"] = "[]"
        if "ingredients_json" not in fields:
            fields["ingredients_json"] = "[]"
    else:
        if "ingredients_json" not in fields:
            fields["ingredients_json"] = "[]"
        ingredients = json.loads(fields["ingredients_json"])
        if not ingredients and fields.get("stub") is False:
            raise ValueError("A finished formule needs ingredients.")
        if not ingredients:
            fields["stub"] = 1
        if "applies_to_json" not in fields:
            fields["applies_to_json"] = "[]"
    recipe_id = _mint_id(conn)
    columns = {
        "id": recipe_id,
        "title": fields.get("title") or "",
        "kind": kind,
        "category": fields.get("category"),
        "voice": fields.get("voice") or "unknown",
        "source": fields.get("source") or "unknown",
        "provenance": fields.get("provenance") or "documented",
        "status": fields.get("status") or "draft",
        "stub": int(fields.get("stub") or 0),
        "needs_practice_review": int(fields.get("needs_practice_review") or 0),
        "favourite": int(fields.get("favourite") or 0),
        "queued_at": fields.get("queued_at"),
        "search_description": fields.get("search_description") or "",
        "method": fields.get("method") or "",
        "notes": fields.get("notes") or "",
        "context": fields.get("context") or "",
        "ocr_text": fields.get("ocr_text") or "",
        "ingredients_json": fields.get("ingredients_json") or "[]",
        "applies_to_json": fields.get("applies_to_json") or "[]",
        "tattva_json": fields.get("tattva_json") or "[]",
        "photos_json": "[]",
        "created_at": stamp,
        "updated_at": stamp,
        "extra_json": "{}",
    }
    conn.execute(
        f"""
        INSERT INTO recipes ({", ".join(columns)})
        VALUES ({", ".join("?" for _ in columns)})
        """,
        tuple(columns.values()),
    )
    kitchen_log.record_event(
        conn,
        "recipe_added",
        ref_id=recipe_id,
        at=stamp,
        title=columns["title"],
        detail=log_detail or "",
        extra={"category": columns.get("category")},
    )
    if columns.get("queued_at"):
        kitchen_log.record_event(
            conn,
            "recipe_planned",
            ref_id=recipe_id,
            at=stamp,
            title=columns["title"],
            extra={"category": columns.get("category")},
        )
    conn.commit()
    return get_recipe(conn, recipe_id)


def edit_recipe(
    conn: sqlite3.Connection,
    recipe_id: str,
    body: dict,
    *,
    now: datetime | None = None,
) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, recipe_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("Recipe changed. Refresh before editing.")
    changes = body.get("changes")
    if changes is None:
        changes = {key: value for key, value in body.items() if key not in ("expected_updated_at", "expectedUpdatedAt", "id")}
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Supply recipe fields to change.")
    stamp = _stamp(now)
    fields = _parse_fields(changes, creating=False, stamp=stamp)
    if not fields:
        raise ValueError("Supply recipe fields to change.")
    if row["provenance"] == "ocr-draft" and fields.get("provenance") not in (None, "ocr-draft"):
        raise ValueError("Keep OCR provenance; record a first cook with needsPracticeReview instead.")
    assignments = []
    values = []
    for column, value in fields.items():
        assignments.append(f"{column} = ?")
        values.append(value)
    assignments.append("updated_at = ?")
    values.append(stamp)
    values.append(recipe_id)
    conn.execute(f"UPDATE recipes SET {', '.join(assignments)} WHERE id = ?", values)
    # Re-validate kind constraints after merge (no get_recipe: that may sweep/commit).
    merged = _public(_row(conn, recipe_id))
    if merged["kind"] == "praxis":
        if not (merged.get("method") or "").strip():
            conn.rollback()
            raise ValueError("Praxis cards require a method.")
    else:
        if not merged.get("ingredients") and merged.get("stub") is False:
            conn.rollback()
            raise ValueError("A finished formule needs ingredients.")
    kind = _edit_log_kind(row, fields)
    if kind:
        kitchen_log.record_event(
            conn,
            kind,
            ref_id=recipe_id,
            at=stamp,
            title=merged["title"],
            extra={"category": merged.get("category")},
        )
    conn.commit()
    return get_recipe(conn, recipe_id)


def delete_recipe(conn: sqlite3.Connection, recipe_id: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, recipe_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("Recipe changed. Refresh before deleting.")
    title = row["title"]
    conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    # Keep the numeric counter at least one past every remaining id.
    numbers = [
        int(match.group(1))
        for (recipe_id_value,) in conn.execute("SELECT id FROM recipes").fetchall()
        for match in [RECIPE_ID.match(recipe_id_value)]
        if match
    ]
    next_id = max([1, *(n + 1 for n in numbers)], default=1)
    current = conn.execute("SELECT next_numeric_id FROM catalog_meta WHERE id = 1").fetchone()[0]
    conn.execute(
        "UPDATE catalog_meta SET next_numeric_id = ? WHERE id = 1",
        (max(current, next_id),),
    )
    conn.commit()
    return {"status": "deleted", "id": recipe_id, "title": title}


def mark_cooked(conn: sqlite3.Connection, recipe_id: str, body: dict, *, now: datetime | None = None) -> dict:
    """Record a cook: clear queue + practice review; maybe mark a slip night.

    Does not place the recipe onto tonight's slip. If the recipe already sits on
    an uncooked night of the current week on or before today, that night is
    marked cooked and its date is the cook date; otherwise the cook date is today.
    """
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    if "needsPracticeReview" in body and body.get("needsPracticeReview") is not False:
        raise ValueError("Mark cooked only clears practice review.")
    row = _row(conn, recipe_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("Recipe changed. Refresh before editing.")
    stamp = _stamp(now)
    today = household_today(conn)
    settings = get_settings(conn)
    week_start = week_start_for(today, settings["week_start_day"]).isoformat()
    night = conn.execute(
        """
        SELECT date FROM nights
        WHERE week_start = ? AND recipe_id = ? AND cooked = 0 AND date <= ?
        ORDER BY date DESC
        LIMIT 1
        """,
        (week_start, recipe_id, today.isoformat()),
    ).fetchone()
    cook_date = night["date"] if night is not None else today.isoformat()
    if night is not None:
        conn.execute(
            "UPDATE nights SET cooked = 1, updated_at = ? WHERE date = ?",
            (stamp, night["date"]),
        )
    conn.execute(
        """
        UPDATE recipes
        SET needs_practice_review = 0, queued_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (stamp, recipe_id),
    )
    kitchen_log.record_event(
        conn,
        "recipe_cooked",
        ref_id=recipe_id,
        at=stamp,
        title=row["title"] or "",
        detail=cook_date,
        extra={"category": row["category"], "date": cook_date},
    )
    conn.commit()
    return get_recipe(conn, recipe_id)


def clear_queue_and_review(
    conn: sqlite3.Connection,
    recipe_id: str,
    *,
    stamp: str,
    cook_date: str | None = None,
) -> None:
    """Slip newly-cooked night: clear queue/review and log one recipe_cooked.

    Every newly cooked night with a recipe writes a cook event (dated cook_date).
    Queue and practice review clear when set. Caller commits.
    """
    row = conn.execute(
        "SELECT title, category, needs_practice_review, queued_at FROM recipes WHERE id = ?",
        (recipe_id,),
    ).fetchone()
    if row is None:
        return
    if row["needs_practice_review"] or row["queued_at"] is not None:
        conn.execute(
            """
            UPDATE recipes
            SET needs_practice_review = 0, queued_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (stamp, recipe_id),
        )
    if cook_date:
        kitchen_log.record_event(
            conn,
            "recipe_cooked",
            ref_id=recipe_id,
            at=stamp,
            title=row["title"] or "",
            detail=cook_date,
            extra={"category": row["category"], "date": cook_date},
        )


def update_photos(
    conn: sqlite3.Connection,
    recipe_id: str,
    body: dict,
    photos_dir: Path,
    *,
    now: datetime | None = None,
) -> dict:
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    row = _row(conn, recipe_id)
    expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
    if expected != row["updated_at"]:
        raise StaleState("Recipe changed. Refresh before changing its photos.")
    photos = list(json.loads(row["photos_json"] or "[]"))
    before_count = len(photos)
    if "remove" in body:
        path = body["remove"]
        if not isinstance(path, str) or path not in photos:
            raise ValueError("Photo is no longer attached to this recipe.")
        photos.remove(path)
    else:
        images = body.get("photos")
        if not isinstance(images, list) or not images:
            raise ValueError("Choose at least one photo.")
        if len(images) > 4:
            raise ValueError("Attach up to four photos.")
        for item in images:
            if isinstance(item, str) and item.startswith("/photos/"):
                stored = "data/cooking-photos/" + Path(item).name
                if stored not in photos and item not in photos:
                    photos.append(stored)
            elif isinstance(item, str) and (item.startswith("data/cooking-photos/") or item.startswith("cooking-photos/")):
                if item not in photos:
                    photos.append(item)
            elif isinstance(item, str) and item.startswith("data:"):
                photos.append(_store_data_url(item, photos_dir))
            else:
                raise ValueError("Use a photo path or a data URL.")
    stamp = _stamp(now)
    conn.execute(
        "UPDATE recipes SET photos_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(photos, ensure_ascii=False), stamp, recipe_id),
    )
    added = len(photos) - before_count
    if added > 0:
        kitchen_log.record_event(
            conn,
            "photo_added",
            ref_id=recipe_id,
            at=stamp,
            title=row["title"] or "",
            detail=str(added),
            extra={"category": row["category"], "count": added},
        )
    conn.commit()
    result = get_recipe(conn, recipe_id)
    return {"ok": True, "status": "saved", "recipe_id": recipe_id, "photos": result["photos"], "recipe": result}


def _store_data_url(raw: str, photos_dir: Path) -> str:
    if len(raw) > 15_000_000:
        raise ValueError("Each photo must be under 10 MB.")
    try:
        header, encoded = raw.split(",", 1)
        blob = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Use a valid JPEG, PNG or WebP cooking photo under 10 MB.") from exc
    if len(blob) > 10 * 1024 * 1024:
        raise ValueError("Photo too large")
    ext = _image_ext(blob)
    photos_dir.mkdir(parents=True, exist_ok=True)
    name = str(uuid.uuid4()) + ext
    (photos_dir / name).write_bytes(blob)
    return "data/cooking-photos/" + name


def _image_ext(blob: bytes) -> str:
    if blob.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("Use a valid JPEG, PNG or WebP cooking photo under 10 MB.")


def _mint_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT next_numeric_id FROM catalog_meta WHERE id = 1").fetchone()
    number = row["next_numeric_id"]
    conn.execute("UPDATE catalog_meta SET next_numeric_id = ? WHERE id = 1", (number + 1,))
    return f"CBK-{number:04d}" if number < 10000 else f"CBK-{number}"


def _row(conn: sqlite3.Connection, recipe_id: str):
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise NotFound("Unknown recipe ID.")
    return row


def _parse_fields(body: dict, *, creating: bool, stamp: str | None = None) -> dict:
    fields = {}
    for key, column in _STRING_FIELDS.items():
        if key not in body:
            continue
        value = body[key]
        if key == "kind":
            fields[column] = _normalize_kind(value)
            continue
        if value is None and key == "category":
            fields[column] = None
            continue
        if not isinstance(value, str):
            raise ValueError("Invalid recipe field: " + key)
        if key == "title" and not value.strip():
            raise ValueError("Cookbook cards require a title.")
        fields[column] = value if key in ("method", "notes", "context", "ocrText", "searchDescription") else value.strip()
        if key == "category" and not fields[column]:
            fields[column] = None
    for key, column in _BOOL_FIELDS.items():
        if key not in body:
            continue
        value = body[key]
        if type(value) is not bool:
            raise ValueError("Invalid recipe field: " + key)
        fields[column] = 1 if value else 0
    for key, column in _LIST_FIELDS.items():
        if key not in body:
            continue
        value = body[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("Invalid recipe field: " + key)
        fields[column] = json.dumps(value, ensure_ascii=False)
    if "queued" in body:
        value = body["queued"]
        if type(value) is not bool:
            raise ValueError("Invalid recipe field: queued")
        if stamp is None:
            stamp = _stamp(None)
        fields["queued_at"] = stamp if value else None
    unknown = (
        set(body)
        - set(_STRING_FIELDS)
        - set(_BOOL_FIELDS)
        - set(_LIST_FIELDS)
        - {"photos", "queued"}
    )
    if creating:
        unknown -= set()
    if unknown and not creating:
        # edits only allow known fields; photos go through update_photos
        bad = sorted(unknown)
        raise ValueError("Recipe field cannot be edited: " + bad[0])
    return fields


def _public(row) -> dict:
    ingredients = json.loads(row["ingredients_json"] or "[]")
    applies_to = json.loads(row["applies_to_json"] or "[]")
    tattva = json.loads(row["tattva_json"] or "[]")
    photos = json.loads(row["photos_json"] or "[]")
    keys = row.keys() if hasattr(row, "keys") else []
    queued_at = row["queued_at"] if "queued_at" in keys else None
    out = {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"] if row["kind"] in _FORM_KINDS else "formule",
        "category": row["category"],
        "voice": row["voice"],
        "source": row["source"],
        "provenance": row["provenance"],
        "status": row["status"],
        "stub": bool(row["stub"]),
        "needsPracticeReview": bool(row["needs_practice_review"]),
        "favourite": bool(row["favourite"]),
        "queuedAt": queued_at,
        "searchDescription": row["search_description"],
        "method": row["method"],
        "notes": row["notes"],
        "context": row["context"],
        "ocrText": row["ocr_text"],
        "ingredients": ingredients,
        "appliesTo": applies_to,
        "tattva": tattva,
        "photos": photos,
        "cookCount": 0,
        "lastCooked": None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    scans = _ocr_photos(row["extra_json"])
    if scans:
        out["ocrPhotos"] = scans
    return out


def _ocr_photos(raw) -> list:
    """Scans ride in extra_json. The page shows the first one as 'from the box'."""
    try:
        extra = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return []
    photos = extra.get("ocrPhotos") if isinstance(extra, dict) else None
    if not isinstance(photos, list) or not all(isinstance(item, str) for item in photos):
        return []
    return photos


def _card(item: dict) -> dict:
    """List row: name, who it came from, and enough text to search."""
    return {
        "id": item["id"],
        "title": item["title"],
        "kind": item["kind"],
        "category": item["category"],
        "source": item["source"],
        "voice": item["voice"],
        "searchDescription": item["searchDescription"],
        "ingredients": item["ingredients"],
        "appliesTo": item["appliesTo"],
        "notes": item["notes"],
        "stub": item["stub"],
        "needsPracticeReview": item["needsPracticeReview"],
        "favourite": item["favourite"],
        "queuedAt": item.get("queuedAt"),
        "cookCount": int(item.get("cookCount") or 0),
        "lastCooked": item.get("lastCooked"),
        "updatedAt": item["updatedAt"],
    }


def _page_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return PAGE_SIZE
    return min(limit, 100)


def _encode_cursor(title: str, recipe_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([title, recipe_id]).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    pad = "=" * (-len(cursor) % 4)
    try:
        title, recipe_id = json.loads(base64.urlsafe_b64decode(cursor + pad))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Bad cursor") from exc
    if not isinstance(title, str) or not isinstance(recipe_id, str):
        raise ValueError("Bad cursor")
    return title, recipe_id


def _edit_log_kind(row, fields: dict) -> str | None:
    """One log line per save: planned, then favourite, else edit.

    Clearing practice review is quiet — cooks are /cooked or the slip toggle.
    Unqueueing, unfavouriting, and repeat same-state saves stay quiet.
    """
    was_queued = row["queued_at"] is not None
    if "queued_at" in fields and not was_queued and fields["queued_at"]:
        return "recipe_planned"
    was_favourite = bool(row["favourite"])
    if "favourite" in fields and not was_favourite and fields["favourite"]:
        return "recipe_favourited"
    material = {key: value for key, value in fields.items() if key != "needs_practice_review"}
    quiet = {"favourite", "queued_at"}
    if set(material) <= quiet:
        favourite_noop = "favourite" not in material or bool(material["favourite"]) == was_favourite or (
            was_favourite and not material["favourite"]
        )
        queue_noop = "queued_at" not in material or (
            (material["queued_at"] is not None) == was_queued
            or (was_queued and material["queued_at"] is None)
        )
        if favourite_noop and queue_noop:
            return None
    return "recipe_edited"


def _sample_with_queue(
    conn: sqlite3.Connection,
    limit: int,
    categories: list[str] | None,
) -> list[dict]:
    """Queued recipes first (oldest), then random fill for the frieze."""
    cat_sql = ""
    cat_args: list = []
    if categories:
        marks = ",".join("?" * len(categories))
        cat_sql = f" AND (category IN ({marks})"
        cat_args.extend(categories)
        if "misc" in categories:
            cat_sql += " OR category IS NULL OR category = ''"
        cat_sql += ")"
    queued_rows = conn.execute(
        f"""
        SELECT * FROM recipes
        WHERE queued_at IS NOT NULL{cat_sql}
        ORDER BY queued_at ASC, id ASC
        LIMIT ?
        """,
        (*cat_args, limit),
    ).fetchall()
    items = [_public(row) for row in queued_rows]
    if len(items) >= limit:
        return items[:limit]
    seen = {item["id"] for item in items}
    need = limit - len(items)
    sql = "SELECT * FROM recipes WHERE 1=1"
    args: list = []
    if categories:
        marks = ",".join("?" * len(categories))
        sql += f" AND (category IN ({marks})"
        args.extend(categories)
        if "misc" in categories:
            sql += " OR category IS NULL OR category = ''"
        sql += ")"
    if seen:
        marks = ",".join("?" * len(seen))
        sql += f" AND id NOT IN ({marks})"
        args.extend(sorted(seen))
    rows = conn.execute(sql + " ORDER BY random() LIMIT ?", (*args, need)).fetchall()
    items.extend(_public(row) for row in rows)
    return items


def _encode_queue_cursor(stamp: str, recipe_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([stamp, recipe_id]).encode()).decode().rstrip("=")


def _decode_queue_cursor(cursor: str) -> tuple[str, str]:
    pad = "=" * (-len(cursor) % 4)
    try:
        stamp, recipe_id = json.loads(base64.urlsafe_b64decode(cursor + pad))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Bad cursor") from exc
    if not isinstance(stamp, str) or not isinstance(recipe_id, str):
        raise ValueError("Bad cursor")
    return stamp, recipe_id


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
