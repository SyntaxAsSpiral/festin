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
    "tattva": "tattva_json",
}


def list_recipes(
    conn: sqlite3.Connection,
    *,
    q: str = "",
    cursor: str | None = None,
    limit: int = PAGE_SIZE,
    sample: bool = False,
    categories: list[str] | None = None,
) -> dict:
    limit = _page_limit(limit)
    if sample:
        # A random handful (the Meals frieze): one page, no cursor, optionally from
        # some categories only ('misc' also takes recipes with no category).
        sql, args = "SELECT * FROM recipes", []
        if categories:
            marks = ",".join("?" * len(categories))
            sql += f" WHERE category IN ({marks})"
            if "misc" in categories:
                sql += " OR category IS NULL OR category = ''"
            args.extend(categories)
        rows = conn.execute(sql + " ORDER BY random() LIMIT ?", (*args, limit)).fetchall()
        return {"recipes": [_card(_public(row)) for row in rows], "nextCursor": None}
    params: list = []
    where = []
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
        title, recipe_id = _decode_cursor(cursor)
        where.append("((title > ?) OR (title = ? AND id > ?))")
        params.extend([title, title, recipe_id])
    sql = "SELECT * FROM recipes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY title COLLATE NOCASE, id LIMIT ?"
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()
    items = [_public(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["title"], last["id"])
    return {"recipes": [_card(item) for item in items], "nextCursor": next_cursor}


def get_recipe(conn: sqlite3.Connection, recipe_id: str) -> dict:
    row = _row(conn, recipe_id)
    return _public(row)


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
    fields = _parse_fields(body, creating=True)
    if not fields.get("title"):
        raise ValueError("Cookbook cards require a title.")
    kind = fields.get("kind") or "recipe"
    if kind == "praxis":
        if not (fields.get("method") or "").strip():
            raise ValueError("Praxis cards require a method.")
    else:
        if "ingredients_json" not in fields:
            fields["ingredients_json"] = "[]"
        ingredients = json.loads(fields["ingredients_json"])
        if not ingredients and fields.get("stub") is False:
            raise ValueError("A finished recipe needs ingredients.")
        if not ingredients:
            fields["stub"] = 1
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
        "search_description": fields.get("search_description") or "",
        "method": fields.get("method") or "",
        "notes": fields.get("notes") or "",
        "context": fields.get("context") or "",
        "ocr_text": fields.get("ocr_text") or "",
        "ingredients_json": fields.get("ingredients_json") or "[]",
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
    fields = _parse_fields(changes, creating=False)
    if not fields:
        raise ValueError("Supply recipe fields to change.")
    if row["provenance"] == "ocr-draft" and fields.get("provenance") not in (None, "ocr-draft"):
        raise ValueError("Keep OCR provenance; record a first cook with needsPracticeReview instead.")
    assignments = []
    values = []
    for column, value in fields.items():
        assignments.append(f"{column} = ?")
        values.append(value)
    stamp = _stamp(now)
    assignments.append("updated_at = ?")
    values.append(stamp)
    values.append(recipe_id)
    conn.execute(f"UPDATE recipes SET {', '.join(assignments)} WHERE id = ?", values)
    # Re-validate kind constraints after merge.
    merged = get_recipe(conn, recipe_id)
    if merged["kind"] == "praxis":
        if not (merged.get("method") or "").strip():
            conn.rollback()
            raise ValueError("Praxis cards require a method.")
    else:
        if not merged.get("ingredients") and merged.get("stub") is False:
            conn.rollback()
            raise ValueError("A finished recipe needs ingredients.")
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
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    if "needsPracticeReview" in body and body.get("needsPracticeReview") is not False:
        raise ValueError("Mark cooked only clears practice review.")
    return edit_recipe(
        conn,
        recipe_id,
        {
            "expected_updated_at": body.get("expected_updated_at", body.get("expectedUpdatedAt")),
            "changes": {"needsPracticeReview": False},
        },
        now=now,
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


def _parse_fields(body: dict, *, creating: bool) -> dict:
    fields = {}
    for key, column in _STRING_FIELDS.items():
        if key not in body:
            continue
        value = body[key]
        if key == "kind":
            if value not in ("recipe", "praxis"):
                raise ValueError("Invalid recipe field: kind")
            fields[column] = value
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
    unknown = set(body) - set(_STRING_FIELDS) - set(_BOOL_FIELDS) - set(_LIST_FIELDS) - {"photos"}
    if creating:
        unknown -= set()
    if unknown and not creating:
        # edits only allow known fields; photos go through update_photos
        bad = sorted(unknown)
        raise ValueError("Recipe field cannot be edited: " + bad[0])
    return fields


def _public(row) -> dict:
    ingredients = json.loads(row["ingredients_json"] or "[]")
    tattva = json.loads(row["tattva_json"] or "[]")
    photos = json.loads(row["photos_json"] or "[]")
    out = {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "category": row["category"],
        "voice": row["voice"],
        "source": row["source"],
        "provenance": row["provenance"],
        "status": row["status"],
        "stub": bool(row["stub"]),
        "needsPracticeReview": bool(row["needs_practice_review"]),
        "favourite": bool(row["favourite"]),
        "searchDescription": row["search_description"],
        "method": row["method"],
        "notes": row["notes"],
        "context": row["context"],
        "ocrText": row["ocr_text"],
        "ingredients": ingredients,
        "tattva": tattva,
        "photos": photos,
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
        "notes": item["notes"],
        "stub": item["stub"],
        "needsPracticeReview": item["needsPracticeReview"],
        "favourite": item["favourite"],
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
    """One log line per save: first cook wins, then favourite, else a plain edit.

    Repeat saves of the same cook/favourite state, and unfavouriting alone, stay quiet.
    """
    was_review = bool(row["needs_practice_review"])
    if "needs_practice_review" in fields and was_review and not fields["needs_practice_review"]:
        return "recipe_cooked"
    was_favourite = bool(row["favourite"])
    if "favourite" in fields and not was_favourite and fields["favourite"]:
        return "recipe_favourited"
    if set(fields) <= {"favourite", "needs_practice_review"}:
        favourite_noop = "favourite" not in fields or bool(fields["favourite"]) == was_favourite or (
            was_favourite and not fields["favourite"]
        )
        review_noop = "needs_practice_review" not in fields or bool(
            fields["needs_practice_review"]
        ) == was_review
        if favourite_noop and review_noop:
            return None
    return "recipe_edited"


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
