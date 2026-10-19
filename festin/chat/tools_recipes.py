"""Cookbook search, analysis, and recipe mutation tools over SQLite."""

from __future__ import annotations

import json
import random
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from festin import log as kitchen_log
from festin.chat.schemas import (
    CONTEXT_CAP,
    DINNER_HISTORY_DAYS,
    PLATE_SLUG_SET,
    PLATE_SLUGS,
    RECIPE_FIELDS,
)
from festin.schema import WEEKDAYS

_RECIPE_ID = re.compile(r"^CBK-(\d+)$")


def ctx_get(ctx: Any, key: str, default=None):
    if isinstance(ctx, dict):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def ctx_today(ctx: Any) -> date:
    value = ctx_get(ctx, "today")
    if isinstance(value, date):
        return value
    return date.today()


def stamp_now(ctx: Any = None) -> str:
    now = ctx_get(ctx, "now") if ctx is not None else None
    instant = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def recipe_public(row) -> dict:
    ingredients = json.loads(row["ingredients_json"] or "[]")
    tattva = json.loads(row["tattva_json"] or "[]")
    photos = json.loads(row["photos_json"] or "[]")
    return {
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


def load_recipes(conn) -> list[dict]:
    return [recipe_public(row) for row in conn.execute("SELECT * FROM recipes")]


def normalize_search(value) -> str:
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def bounded_int(value, default, low, high, label, clamp=False) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer.")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{label} must be an integer.")
        value = int(value)
    elif not isinstance(value, int):
        raise ValueError(f"{label} must be an integer.")
    if value < low or (value > high and not clamp):
        raise ValueError(f"{label} must be from {low} to {high}.")
    return min(value, high)


def flag(value, label) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be true or false.")
    return value


def string_list(value, label) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be text or a list of text.")
    return [item.strip() for item in value if item.strip()]


def catalog_filters(args: dict) -> dict:
    filters: dict = {}
    slugs = []
    for raw in string_list(args.get("category"), "category"):
        slug = next((name for name in PLATE_SLUGS if name == raw.casefold()), None)
        if slug is None:
            raise ValueError("Unknown category. Use a plate slug, not uncategorized.")
        if slug not in slugs:
            slugs.append(slug)
    if slugs:
        filters["category"] = slugs
    kinds = []
    for raw in string_list(args.get("kind"), "kind"):
        kind = raw.casefold()
        if kind not in ("recipe", "praxis"):
            raise ValueError("kind is recipe or praxis.")
        if kind not in kinds:
            kinds.append(kind)
    if kinds:
        filters["kind"] = kinds
    for key in ("voice", "source", "status", "tattva"):
        folded = []
        for raw in string_list(args.get(key), key):
            text = normalize_search(raw)
            if text and text not in folded:
                folded.append(text)
        if folded:
            filters[key] = folded
    if "favourite" in args and args.get("favourite") is not None:
        filters["favourite"] = flag(args.get("favourite"), "favourite")
    return filters


def entry_kind(row: dict) -> str:
    return "praxis" if row.get("kind") == "praxis" else "recipe"


def row_in_scope(recipe: dict, filters: dict) -> bool:
    if "category" in filters and recipe.get("category") not in filters["category"]:
        return False
    if "kind" in filters and entry_kind(recipe) not in filters["kind"]:
        return False
    for key in ("voice", "source", "status"):
        if key in filters and normalize_search(recipe.get(key) or "") not in filters[key]:
            return False
    if "tattva" in filters:
        have = {normalize_search(item) for item in recipe.get("tattva") or [] if isinstance(item, str)}
        if not have & set(filters["tattva"]):
            return False
    if "favourite" in filters and bool(recipe.get("favourite")) != filters["favourite"]:
        return False
    return True


def searchable_text(recipe: dict) -> str:
    parts = []
    for key in ("title", "searchDescription", "method", "ocrText", "notes", "voice", "source"):
        value = recipe.get(key)
        if isinstance(value, str):
            parts.append(value)
    ingredients = recipe.get("ingredients")
    if isinstance(ingredients, list):
        parts.extend(item for item in ingredients if isinstance(item, str))
    return normalize_search("\n".join(parts))


def stored_category(recipe: dict | None):
    if not isinstance(recipe, dict):
        return None
    category = recipe.get("category")
    return category if category in PLATE_SLUG_SET else None


def stored_tattva(recipe: dict) -> list[str]:
    tattva = recipe.get("tattva")
    return [item for item in tattva if isinstance(item, str)] if isinstance(tattva, list) else []


def compact_card(recipe: dict) -> dict:
    voice = recipe.get("voice")
    description = recipe.get("searchDescription")
    return {
        "id": recipe.get("id"),
        "title": recipe.get("title") or "",
        "category": stored_category(recipe),
        "kind": entry_kind(recipe),
        "voice": voice if isinstance(voice, str) else "",
        "tattva": stored_tattva(recipe),
        "searchDescription": description if isinstance(description, str) else "",
        "favourite": bool(recipe.get("favourite")),
    }


def card_summary(recipe: dict) -> dict:
    voice = recipe.get("voice")
    source = recipe.get("source")
    return {
        "id": recipe.get("id"),
        "title": recipe.get("title") or "",
        "category": stored_category(recipe),
        "kind": entry_kind(recipe),
        "voice": voice if isinstance(voice, str) else None,
        "source": source if isinstance(source, str) else None,
        "stub": bool(recipe.get("stub")),
        "tattva": stored_tattva(recipe),
    }


def sorted_counts(counts: dict) -> dict:
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def top_counts(counts: dict, limit: int = 10) -> dict:
    ordered = sorted_counts(counts)
    if len(ordered) <= limit:
        return ordered
    kept = dict(list(ordered.items())[:limit])
    kept["other"] = sum(list(ordered.values())[limit:])
    return kept


def search_cookbook(args: dict, ctx: Any) -> dict:
    if not isinstance(args, dict):
        raise ValueError("Search needs a query or a filter.")
    raw_query = args.get("query") or ""
    if not isinstance(raw_query, str):
        raise ValueError("Query must be text.")
    filters = catalog_filters(args)
    limit = bounded_int(args.get("limit"), 40, 1, 100, "limit", clamp=True)
    offset = bounded_int(args.get("offset"), 0, 0, 100000, "offset")
    full = flag(args.get("full"), "full")
    query_text = normalize_search(raw_query)
    words = query_text.split()
    matches = []
    for recipe in load_recipes(ctx_get(ctx, "conn")):
        if not row_in_scope(recipe, filters):
            continue
        exact_id = bool(query_text) and query_text == normalize_search(recipe.get("id", ""))
        if words and not exact_id and not all(word in searchable_text(recipe) for word in words):
            continue
        title = normalize_search(recipe.get("title", ""))
        rank = (
            exact_id,
            query_text == title,
            sum(word in title for word in words),
            bool(query_text) and query_text in title,
        )
        matches.append((rank, recipe))
    matches.sort(key=lambda match: match[0], reverse=True)
    page = [recipe for _, recipe in matches[offset : offset + limit]]
    return {
        "total": len(matches),
        "limit": limit,
        "offset": offset,
        "results": page if full else [compact_card(recipe) for recipe in page],
    }


def dinner_title_key(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.split())


def unique_dinner_id(title, rows) -> str | None:
    key = dinner_title_key(title)
    if not key:
        return None
    hits = [
        row["id"]
        for row in rows
        if entry_kind(row) != "praxis" and dinner_title_key(row.get("title", "")) == key
    ]
    return hits[0] if len(hits) == 1 else None


def _dinner_rows(conn, today: date, days: int = DINNER_HISTORY_DAYS) -> list[dict]:
    floor = (today - timedelta(days=days - 1)).isoformat()
    ceiling = today.isoformat()
    rows = conn.execute(
        """
        SELECT n.date, n.recipe_id, n.title, n.week_start, r.category, r.kind
        FROM nights n
        LEFT JOIN recipes r ON r.id = n.recipe_id
        WHERE n.date >= ? AND n.date <= ?
        ORDER BY n.date
        """,
        (floor, ceiling),
    ).fetchall()
    dinners = []
    for row in rows:
        title = (row["title"] or "").strip()
        if not title or "leftover" in title.casefold():
            continue
        link = (row["recipe_id"] or "").strip()
        dinners.append(
            {
                "date": row["date"],
                "dinner": f"{link} {title}" if link else title,
                "recipe_id": link or None,
                "category": row["category"] if row["category"] in PLATE_SLUG_SET else None,
            }
        )
    return dinners


def last_cooked_dates(dinners: list[dict]) -> dict[str, str]:
    last: dict[str, str] = {}
    for dinner in dinners:
        rid = dinner.get("recipe_id")
        if not rid:
            text = str(dinner.get("dinner") or "")
            match = re.match(r"(CBK-\d+)\b", text)
            rid = match.group(1) if match else None
        if not rid:
            continue
        when = str(dinner.get("date") or "")
        if when >= last.get(rid, ""):
            last[rid] = when
    return last


def not_cooked_examples(rows, cooked_categories, last_cooked, rng=None) -> list[dict]:
    if rng is None:
        rng = random.Random()
    pooled: dict[str, list] = {}
    for row in rows:
        if entry_kind(row) == "praxis":
            continue
        category = stored_category(row)
        if not category or category in cooked_categories:
            continue
        pooled.setdefault(category, []).append(row)
    found = []
    for category in sorted(pooled):
        buckets: dict[str, list] = {}
        for row in pooled[category]:
            when = last_cooked.get(row.get("id")) or ""
            buckets.setdefault(when, []).append(row)
        ordered = []
        for when in sorted(buckets):
            bucket = buckets[when]
            rng.shuffle(bucket)
            ordered.extend(bucket)
        examples = [{"id": row.get("id"), "title": row.get("title") or ""} for row in ordered[:3]]
        if examples:
            found.append({"category": category, "examples": examples})
    return found


def present_week(conn, week_row) -> dict:
    start = date.fromisoformat(week_row["start_date"])
    nights = {
        row["date"]: row
        for row in conn.execute(
            "SELECT * FROM nights WHERE week_start = ? ORDER BY date",
            (week_row["start_date"],),
        ).fetchall()
    }
    days = []
    for index, day in enumerate(WEEKDAYS):
        when = (start + timedelta(days=index)).isoformat()
        night = nights.get(when)
        ingredients = [
            item["text"]
            for item in conn.execute(
                "SELECT text FROM night_ingredients WHERE date = ? ORDER BY position",
                (when,),
            ).fetchall()
        ]
        if night is None:
            days.append({"day": day, "recipe": None, "title": "", "ingredients": []})
        else:
            days.append(
                {
                    "day": day,
                    "recipe": night["recipe_id"],
                    "title": night["title"],
                    "ingredients": ingredients,
                }
            )
    return {
        "weekStart": week_row["start_date"],
        "notes": week_row["notes"],
        "updatedAt": week_row["updated_at"],
        "days": days,
        "slipTitle": week_row["slip_title"],
    }


def recent_plans(conn, limit: int = 8) -> list[dict]:
    weeks = conn.execute(
        "SELECT * FROM weeks ORDER BY start_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [present_week(conn, week) for week in weeks]


def analyze_cookbook(args: dict, ctx: Any) -> dict:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("Catalog analysis needs a scope object.")
    conn = ctx_get(ctx, "conn")
    filters = catalog_filters(args)
    rows = load_recipes(conn)
    scoped = [row for row in rows if row_in_scope(row, filters)]
    by_category: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_voice: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_tattva: dict[str, int] = {}
    for row in scoped:
        category = stored_category(row) or "uncategorized"
        by_category[category] = by_category.get(category, 0) + 1
        kind = entry_kind(row)
        by_kind[kind] = by_kind.get(kind, 0) + 1
        voice = row.get("voice")
        voice = voice.strip().casefold() if isinstance(voice, str) and voice.strip() else "unknown"
        by_voice[voice] = by_voice.get(voice, 0) + 1
        source = row.get("source")
        source = source.strip() if isinstance(source, str) and source.strip() else "unknown"
        by_source[source] = by_source.get(source, 0) + 1
        tattvas = [item.strip() for item in stored_tattva(row) if item.strip()]
        if not tattvas:
            by_tattva["none"] = by_tattva.get("none", 0) + 1
        else:
            for name in tattvas:
                by_tattva[name] = by_tattva.get(name, 0) + 1
    briefs = [card_summary(row) for row in scoped]
    dinners = _dinner_rows(conn, ctx_today(ctx))
    for item in dinners:
        if item.get("category") is None and item.get("recipe_id"):
            card = next((r for r in rows if r.get("id") == item["recipe_id"]), None)
            item["category"] = stored_category(card)
        # Public shape matches live: date, dinner, category.
        item.pop("recipe_id", None)
    report = {
        "count": len(scoped),
        "scope": filters,
        "counts": {
            "category": sorted_counts(by_category),
            "kind": sorted_counts(by_kind),
            "voice": top_counts(by_voice),
            "source": top_counts(by_source),
            "tattva": sorted_counts(by_tattva),
        },
        "stubs": [row for row in briefs if row["stub"] and row["kind"] != "praxis"],
        "praxis": [row for row in briefs if row["kind"] == "praxis"],
        "dinner_history": {"days": DINNER_HISTORY_DAYS, "dinners": dinners},
        "not_cooked": not_cooked_examples(
            scoped,
            {item["category"] for item in dinners if item.get("category")},
            last_cooked_dates(_dinner_rows(conn, ctx_today(ctx), days=36500)),
        ),
        "recent_plans": recent_plans(conn),
    }
    if filters or flag(args.get("list"), "list"):
        report["recipes"] = briefs
    return report


def stale_recipe_edit(row: dict, changes) -> str:
    if isinstance(changes, dict):
        current = {key: row.get(key) for key in changes}
    else:
        current = compact_card(row)
    stamp = row.get("updatedAt")
    return (
        "Recipe changed or revision missing. Read it again before editing. "
        "Retry once with expected_updated_at="
        + json.dumps(stamp, ensure_ascii=False)
        + ". Current values: "
        + json.dumps({"updatedAt": stamp, "fields": current}, ensure_ascii=False)
        + " Tell zk this save did not happen."
    )


def _recipe_row(conn, recipe_id: str):
    row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown recipe ID.")
    return row


def _mint_id(conn) -> str:
    number = conn.execute("SELECT next_numeric_id FROM catalog_meta WHERE id = 1").fetchone()[0]
    conn.execute("UPDATE catalog_meta SET next_numeric_id = ? WHERE id = 1", (number + 1,))
    return f"CBK-{number:04d}" if number < 10000 else f"CBK-{number}"


def _validate_field(field: str, value) -> None:
    schema = RECIPE_FIELDS.get(field)
    if schema is None:
        raise ValueError("Recipe field cannot be edited: " + field)
    kind = schema["type"]
    valid = (
        isinstance(value, str)
        if kind == "string"
        else type(value) is bool
        if kind == "boolean"
        else isinstance(value, list) and all(isinstance(i, str) and i.strip() for i in value)
    )
    if valid and kind == "string" and schema.get("minLength") and not value.strip():
        valid = False
    if not valid or ("enum" in schema and value not in schema["enum"]):
        raise ValueError("Invalid recipe field: " + field)


def _apply_changes_to_public(row: dict, changes: dict) -> dict:
    merged = dict(row)
    for field, value in changes.items():
        _validate_field(field, value)
        merged[field] = value
    return merged


def _tool_edit_log_kind(original: dict, changes: dict) -> str | None:
    """One log line per Babette edit: first cook wins, then favourite, else edit."""
    was_review = bool(original.get("needsPracticeReview"))
    if (
        "needsPracticeReview" in changes
        and was_review
        and changes.get("needsPracticeReview") is False
    ):
        return "recipe_cooked"
    was_favourite = bool(original.get("favourite"))
    if "favourite" in changes and not was_favourite and changes.get("favourite") is True:
        return "recipe_favourited"
    if set(changes) <= {"favourite", "needsPracticeReview"}:
        favourite_noop = "favourite" not in changes or bool(changes.get("favourite")) == was_favourite or (
            was_favourite and changes.get("favourite") is False
        )
        review_noop = "needsPracticeReview" not in changes or bool(
            changes.get("needsPracticeReview")
        ) == was_review
        if favourite_noop and review_noop:
            return None
    return "recipe_edited"


def _write_public(conn, public: dict, *, creating: bool, stamp: str) -> None:
    columns = (
        public["id"],
        public["title"],
        entry_kind(public),
        public.get("category"),
        public.get("voice") or "",
        public.get("source") or "",
        public.get("provenance"),
        public.get("status"),
        1 if public.get("stub") else 0,
        1 if public.get("needsPracticeReview") else 0,
        1 if public.get("favourite") else 0,
        public.get("searchDescription") or "",
        public.get("method") or "",
        public.get("notes") or "",
        public.get("context") or "",
        public.get("ocrText") or "",
        json.dumps(public.get("ingredients") or [], ensure_ascii=False),
        json.dumps(public.get("tattva") or [], ensure_ascii=False),
        json.dumps(public.get("photos") or [], ensure_ascii=False),
        public.get("createdAt"),
        stamp,
        "{}",
    )
    if creating:
        conn.execute(
            """
            INSERT INTO recipes (
                id, title, kind, category, voice, source, provenance, status, stub,
                needs_practice_review, favourite, search_description, method, notes, context, ocr_text,
                ingredients_json, tattva_json, photos_json, created_at, updated_at, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            columns,
        )
    else:
        conn.execute(
            """
            UPDATE recipes SET
                title = ?, kind = ?, category = ?, voice = ?, source = ?, provenance = ?,
                status = ?, stub = ?, needs_practice_review = ?, favourite = ?,
                search_description = ?, method = ?, notes = ?, context = ?, ocr_text = ?,
                ingredients_json = ?, tattva_json = ?, photos_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                columns[1],
                columns[2],
                columns[3],
                columns[4],
                columns[5],
                columns[6],
                columns[7],
                columns[8],
                columns[9],
                columns[10],
                columns[11],
                columns[12],
                columns[13],
                columns[14],
                columns[15],
                columns[16],
                columns[17],
                columns[18],
                stamp,
                public["id"],
            ),
        )


def manage_recipe(name: str, args: dict, ctx: Any) -> dict:
    if name not in ("add_recipe", "edit_recipe", "delete_recipe"):
        raise ValueError("Unknown cookbook action.")
    conn = ctx_get(ctx, "conn")
    creating = name == "add_recipe"
    if creating:
        changes = args
        # A new card is filed and described on arrival, so search and the plates work.
        if args.get("category") not in PLATE_SLUGS:
            raise ValueError("Give the new card a category: one of " + ", ".join(PLATE_SLUGS) + ".")
        if not str(args.get("searchDescription") or "").strip():
            raise ValueError("Give the new card a searchDescription: one or two sentences on what the dish is.")
        row = {
            "voice": "Babette",
            "source": "",
            "provenance": "generated",
            "status": "draft",
            "photos": [],
            "ocrText": "",
            "notes": "",
            "context": "",
            "searchDescription": "",
            "method": "",
            "ingredients": [],
            "tattva": [],
            "stub": False,
            "needsPracticeReview": False,
            "favourite": False,
        }
    else:
        db_row = _recipe_row(conn, args.get("recipe_id"))
        row = recipe_public(db_row)
        if args.get("expected_updated_at") != row.get("updatedAt"):
            if name == "edit_recipe":
                raise ValueError(stale_recipe_edit(row, args.get("changes")))
            raise ValueError("Recipe changed or revision missing. Read it again before editing.")
        if name == "delete_recipe":
            title = row.get("title", "")
            recipe_id = row["id"]
            conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            numbers = [
                int(match.group(1))
                for (value,) in conn.execute("SELECT id FROM recipes").fetchall()
                for match in [_RECIPE_ID.match(value)]
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
        changes = args.get("changes") if name == "edit_recipe" else {}
    if not isinstance(changes, dict) or (name == "edit_recipe" and not changes):
        raise ValueError("Supply recipe fields to change.")
    for field, value in changes.items():
        _validate_field(field, value)
    row = _apply_changes_to_public(row, changes)
    kind = entry_kind(row)
    if creating:
        row["kind"] = kind
    if not isinstance(row.get("title"), str) or not row["title"].strip():
        raise ValueError("Cookbook cards require a title.")
    if kind == "praxis":
        if not isinstance(row.get("method"), str) or not row["method"].strip():
            raise ValueError("Praxis cards require a method.")
    else:
        if "ingredients" not in row:
            raise ValueError("Recipes require a title and ingredients list (empty for a name-only stub).")
        if not row["ingredients"]:
            if row.get("stub") is False:
                raise ValueError("A finished recipe needs ingredients.")
            row["stub"] = True
    original = None
    if not creating:
        original = recipe_public(_recipe_row(conn, row["id"]))
        if original.get("provenance") == "ocr-draft" and row.get("provenance") != "ocr-draft":
            raise ValueError("Keep OCR provenance; record a first cook with needsPracticeReview instead.")
    stamp = stamp_now(ctx)
    if creating:
        row["id"] = _mint_id(conn)
        row["createdAt"] = stamp
        row["updatedAt"] = stamp
        _write_public(conn, row, creating=True, stamp=stamp)
        kitchen_log.record_event(
            conn,
            "recipe_added",
            ref_id=row["id"],
            at=stamp,
            title=row.get("title") or "",
            extra={"category": row.get("category")},
        )
    else:
        row["updatedAt"] = stamp
        _write_public(conn, row, creating=False, stamp=stamp)
        log_kind = _tool_edit_log_kind(original, changes)
        if log_kind:
            kitchen_log.record_event(
                conn,
                log_kind,
                ref_id=row["id"],
                at=stamp,
                title=row.get("title") or "",
                extra={"category": row.get("category")},
            )
    conn.commit()
    saved = recipe_public(_recipe_row(conn, row["id"]))
    return {"status": "saved", "id": saved["id"], "title": saved["title"], "recipe": saved}


def add_recipe(args: dict, ctx: Any) -> dict:
    return manage_recipe("add_recipe", args, ctx)


def edit_recipe(args: dict, ctx: Any) -> dict:
    return manage_recipe("edit_recipe", args, ctx)


def delete_recipe(args: dict, ctx: Any) -> dict:
    return manage_recipe("delete_recipe", args, ctx)


def append_recipe_context(args: dict, ctx: Any) -> dict:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Context text must be non-empty.")
    text = text.strip()
    conn = ctx_get(ctx, "conn")
    db_row = _recipe_row(conn, args.get("recipe_id"))
    row = recipe_public(db_row)
    if args.get("expected_updated_at") != row.get("updatedAt"):
        raise ValueError("Recipe changed or revision missing. Read it again before editing.")
    existing = row.get("context")
    if existing is None:
        existing = ""
    if isinstance(existing, list):
        raise ValueError("Recipe context is a list; expected a plain string.")
    if not isinstance(existing, str):
        raise ValueError("Recipe context must be a plain string.")
    combined = existing + "\n\n" + text if existing else text
    if len(combined) > CONTEXT_CAP:
        raise ValueError(f"Recipe context is full ({len(existing)} of {CONTEXT_CAP} characters).")
    stamp = stamp_now(ctx)
    conn.execute(
        "UPDATE recipes SET context = ?, updated_at = ? WHERE id = ?",
        (combined, stamp, row["id"]),
    )
    conn.commit()
    saved = recipe_public(_recipe_row(conn, row["id"]))
    return {"status": "saved", "id": saved["id"], "title": saved["title"], "recipe": saved}


def _shared_chat_photos(conn) -> set[str]:
    shared: set[str] = set()
    for row in conn.execute("SELECT extra_json FROM chat_messages WHERE role = 'user'"):
        try:
            extra = json.loads(row["extra_json"] or "{}")
        except json.JSONDecodeError:
            continue
        photos = extra.get("photos") or []
        if isinstance(photos, list):
            for path in photos:
                if isinstance(path, str):
                    shared.add(path)
    return shared


def attach_recipe_photos(args: dict, ctx: Any) -> dict:
    conn = ctx_get(ctx, "conn")
    data_dir = Path(ctx_get(ctx, "data_dir") or ".")
    photos_root = (data_dir / "photos").resolve()
    db_row = _recipe_row(conn, args.get("recipe_id"))
    row = recipe_public(db_row)
    if args.get("expected_updated_at") != row.get("updatedAt"):
        raise ValueError("Recipe changed. Refresh before changing its photos.")
    paths = args.get("photo_paths")
    if not isinstance(paths, list) or not 1 <= len(paths) <= 4 or not all(isinstance(p, str) for p in paths):
        raise ValueError("Choose one to four shared photos.")
    shared = _shared_chat_photos(conn)
    photos = list(row.get("photos") or [])
    before_count = len(photos)
    for path in paths:
        name = Path(path).name
        expected = "/photos/" + name
        file = (photos_root / name).resolve()
        try:
            under_root = file.is_relative_to(photos_root)
        except (ValueError, AttributeError):
            under_root = str(file).startswith(str(photos_root) + "/")
        if path not in shared or path != expected or not under_root:
            raise ValueError("Choose a photo already shared in chat.")
        if not file.is_file():
            raise ValueError("That photo was shared, but its file is not in this kitchen's photos folder.")
        if expected not in photos and path not in photos:
            photos.append(expected)
    stamp = stamp_now(ctx)
    conn.execute(
        "UPDATE recipes SET photos_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(photos, ensure_ascii=False), stamp, row["id"]),
    )
    added = len(photos) - before_count
    if added > 0:
        kitchen_log.record_event(
            conn,
            "photo_added",
            ref_id=row["id"],
            at=stamp,
            title=row.get("title") or "",
            detail=str(added),
            extra={"category": row.get("category"), "count": added},
        )
    conn.commit()
    result = {"ok": True, "status": "saved", "recipe_id": row["id"], "photos": photos}
    if row.get("needsPracticeReview"):
        result["message"] = (
            "Cooking photos are on this card. If the household cooked this dish, "
            "call edit_recipe with only needsPracticeReview set to false. "
            "Do not change provenance or status. If more than one card could be meant, ask which one."
        )
    return result
