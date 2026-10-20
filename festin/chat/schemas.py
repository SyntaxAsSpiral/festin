"""OpenAI tool schemas and trace labels for the core kitchen tools.

Structure (types, enums, required, limits) lives here. Model-facing prose
lives in festin/data/tools.yaml and is read on each tool_specs() call.
"""

from __future__ import annotations

from pathlib import Path

from festin.chat.persona import fill_placeholders, load_blocks
from festin.schema import NOTE_COLORS, WEEKDAYS

PLATE_SLUGS = (
    "breads",
    "cakes",
    "pies-tarts",
    "cookies",
    "casseroles",
    "soups-stews",
    "fish-seafood",
    "chicken",
    "meats",
    "pasta",
    "salads-sides",
    "pantry-party",
    "sweets",
    "sauces-dressings",
    "drinks",
    "pickles-preserves",
    "eggs-breakfast",
    "seasonings",
    "snacks-sandwiches",
    "kitchen-craft",
    "misc",
)
PLATE_SLUG_SET = frozenset(PLATE_SLUGS)
PLATE_SLUG_TEXT = ", ".join(PLATE_SLUGS)

NOTE_COLOR_CHOICES = NOTE_COLORS  # includes none
CONTEXT_LANES = ("household", "preferences", "restrictions")
CONTEXT_LIMITS = {"household": 800, "preferences": 800, "restrictions": 1000}
OPEN_NOTE_CAP = 25
CONTEXT_CAP = 1500
DINNER_HISTORY_DAYS = 60
SCRATCH_LIMIT = 800

DEFAULT_TOOLS = Path(__file__).resolve().parent.parent / "data" / "tools.yaml"

# Structure only — descriptions come from tools.yaml via tool_specs().
RECIPE_FIELDS = {
    "title": {"type": "string", "minLength": 1},
    "kind": {
        "type": "string",
        "enum": ["formule", "praxis", "recipe"],
    },
    "ingredients": {"type": "array", "items": {"type": "string"}},
    "appliesTo": {
        "type": "array",
        "items": {"type": "string"},
    },
    "notes": {"type": "string"},
    "context": {"type": "string"},
    "method": {"type": "string"},
    "voice": {
        "type": "string",
        "minLength": 1,
    },
    "source": {"type": "string"},
    "provenance": {
        "type": "string",
        "enum": ["documented", "reconstructed", "mentioned", "ocr-draft", "confirmed", "generated"],
    },
    "stub": {"type": "boolean"},
    "favourite": {"type": "boolean"},
    "queued": {"type": "boolean"},
    "cooked": {"type": "boolean"},
    "tattva": {"type": "array", "items": {"type": "string"}},
    "searchDescription": {
        "type": "string",
        "maxLength": 300,
    },
    "category": {
        "type": "string",
        "enum": list(PLATE_SLUGS),
    },
}

RECIPE_REVISION = {
    "recipe_id": {"type": "string"},
    "expected_updated_at": {"type": "string"},
}

NOTE_REFERENCE = {
    "id": {"type": "string"},
    "original": {"type": "string"},
    "type": {"type": "string"},
    "open": {"type": "boolean"},
    "color": {"type": "string", "enum": list(NOTE_COLOR_CHOICES)},
    "band": {"type": "string"},
    "priority": {"type": "string", "enum": ["high", "normal", "low"]},
}

_RECIPE_FIELD_TEXT = (
    "kind",
    "appliesTo",
    "notes",
    "context",
    "voice",
    "source",
    "provenance",
    "favourite",
    "queued",
    "cooked",
    "searchDescription",
    "category",
)
_FILTER_FIELD_TEXT = (
    "category",
    "kind",
    "voice",
    "source",
    "tattva",
    "status",
    "favourite",
    "queued",
)
_CORE_TOOL_NAMES = (
    "attach_recipe_photos",
    "add_recipe",
    "edit_recipe",
    "append_recipe_context",
    "delete_recipe",
    "search_history",
    "read_chat_history",
    "search_cookbook",
    "analyze_cookbook",
    "search_notes",
    "analyze_notes",
    "read_notes",
    "edit_note",
    "delete_note",
    "keep_note",
    "update_household_context",
    "set_scratch",
    "propose_dinners",
)


def string_array(enum=None) -> dict:
    item: dict = {"type": "string"}
    if enum is not None:
        item["enum"] = list(enum)
    return {"type": "array", "items": item}


def placeholder_values() -> dict[str, object]:
    return {
        "plate_slugs": PLATE_SLUG_TEXT,
        "open_note_cap": OPEN_NOTE_CAP,
        "context_cap": CONTEXT_CAP,
        "dinner_history_days": DINNER_HISTORY_DAYS,
        "household_limit": CONTEXT_LIMITS["household"],
        "preferences_limit": CONTEXT_LIMITS["preferences"],
        "restrictions_limit": f"{CONTEXT_LIMITS['restrictions']:,}",
    }


def load_tool_text(
    path: str | Path | None = None,
    values: dict[str, object] | None = None,
) -> dict[str, str]:
    source = Path(path) if path is not None else DEFAULT_TOOLS
    blocks = load_blocks(source)
    fill = placeholder_values() if values is None else values
    return {key: fill_placeholders(body, fill) for key, body in blocks.items()}


def _require(text: dict[str, str], key: str) -> str:
    if key not in text:
        raise ValueError("Missing tool text: " + key)
    return text[key]


def _with_desc(spec: dict, description: str) -> dict:
    return {**spec, "description": description}


def _recipe_fields(text: dict[str, str]) -> dict:
    fields = {key: dict(spec) for key, spec in RECIPE_FIELDS.items()}
    for key in _RECIPE_FIELD_TEXT:
        fields[key] = _with_desc(fields[key], _require(text, "fields." + key))
    return fields


def _note_reference(text: dict[str, str]) -> dict:
    fields = {key: dict(spec) for key, spec in NOTE_REFERENCE.items()}
    fields["original"] = _with_desc(fields["original"], _require(text, "fields.note.original"))
    fields["band"] = _with_desc(fields["band"], _require(text, "fields.note.band"))
    return fields


def _catalog_filters(text: dict[str, str]) -> dict:
    base = {
        "category": string_array(PLATE_SLUGS),
        "kind": string_array(("formule", "praxis", "recipe")),
        "voice": string_array(),
        "source": string_array(),
        "tattva": string_array(),
        "status": string_array(),
        "favourite": {"type": "boolean"},
        "queued": {"type": "boolean"},
    }
    return {
        key: _with_desc(base[key], _require(text, "filters." + key))
        for key in _FILTER_FIELD_TEXT
    }


def _expected_updated_at(text: dict[str, str]) -> dict:
    return {
        "type": ["string", "null"],
        "description": _require(text, "fields.expected_updated_at"),
    }


def _search_cookbook_schema(text: dict[str, str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": _require(text, "search_cookbook.query"),
            },
            **_catalog_filters(text),
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "offset": {"type": "integer", "minimum": 0},
            "full": {
                "type": "boolean",
                "description": _require(text, "search_cookbook.full"),
            },
        },
        "additionalProperties": False,
    }


def _analyze_cookbook_schema(text: dict[str, str]) -> dict:
    return {
        "type": "object",
        "properties": {
            **_catalog_filters(text),
            "list": {
                "type": "boolean",
                "description": _require(text, "analyze_cookbook.list"),
            },
        },
        "additionalProperties": False,
    }


def tool_specs(path: str | Path | None = None) -> list[tuple[str, str, dict]]:
    """Assemble (name, description, parameters) from structure + tools.yaml.

    Reads the YAML on every call so edits apply on the next reply.
    """
    text = load_tool_text(path)
    recipe_fields = _recipe_fields(text)
    note_reference = _note_reference(text)
    expected = _expected_updated_at(text)

    specs: list[tuple[str, str, dict]] = [
        (
            "attach_recipe_photos",
            _require(text, "attach_recipe_photos"),
            {
                "type": "object",
                "properties": {
                    "recipe_id": {"type": "string"},
                    "expected_updated_at": expected,
                    "photo_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 4,
                    },
                },
                "required": ["recipe_id", "expected_updated_at", "photo_paths"],
                "additionalProperties": False,
            },
        ),
        (
            "add_recipe",
            _require(text, "add_recipe"),
            {
                "type": "object",
                "properties": recipe_fields,
                "required": ["title", "category", "searchDescription"],
                "additionalProperties": False,
            },
        ),
        (
            "edit_recipe",
            _require(text, "edit_recipe"),
            {
                "type": "object",
                "properties": {
                    **RECIPE_REVISION,
                    "changes": {
                        "type": "object",
                        "properties": recipe_fields,
                        "additionalProperties": False,
                    },
                },
                "required": ["recipe_id", "expected_updated_at", "changes"],
                "additionalProperties": False,
            },
        ),
        (
            "append_recipe_context",
            _require(text, "append_recipe_context"),
            {
                "type": "object",
                "properties": {
                    "recipe_id": {"type": "string"},
                    "expected_updated_at": expected,
                    "text": {"type": "string", "minLength": 1, "maxLength": 1500},
                },
                "required": ["recipe_id", "expected_updated_at", "text"],
                "additionalProperties": False,
            },
        ),
        (
            "delete_recipe",
            _require(text, "delete_recipe"),
            {
                "type": "object",
                "properties": {
                    "recipe_id": {"type": "string"},
                    "expected_updated_at": {"type": ["string", "null"]},
                },
                "required": ["recipe_id", "expected_updated_at"],
                "additionalProperties": False,
            },
        ),
        (
            "search_history",
            _require(text, "search_history"),
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "days": {"type": "integer", "minimum": 1, "maximum": 365},
                    "limit": {"type": "integer"},
                },
            },
        ),
        (
            "read_chat_history",
            _require(text, "read_chat_history"),
            {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string"},
                    "start": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["chat_id"],
            },
        ),
        (
            "search_cookbook",
            _require(text, "search_cookbook"),
            _search_cookbook_schema(text),
        ),
        (
            "analyze_cookbook",
            _require(text, "analyze_cookbook"),
            _analyze_cookbook_schema(text),
        ),
        (
            "search_notes",
            _require(text, "search_notes"),
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        (
            "analyze_notes",
            _require(text, "analyze_notes"),
            {"type": "object", "properties": {}, "additionalProperties": False},
        ),
        (
            "read_notes",
            _require(text, "read_notes"),
            {"type": "object", "properties": {}, "additionalProperties": False},
        ),
        (
            "edit_note",
            _require(text, "edit_note"),
            {
                "type": "object",
                "properties": {
                    **note_reference,
                    "text": {"type": "string", "maxLength": 16000},
                },
                "required": ["original", "text"],
                "additionalProperties": False,
            },
        ),
        (
            "delete_note",
            _require(text, "delete_note"),
            {
                "type": "object",
                "properties": note_reference,
                "required": ["id", "original"],
                "additionalProperties": False,
            },
        ),
        (
            "keep_note",
            _require(text, "keep_note"),
            {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "text": {"type": "string"},
                    "open": {"type": "boolean"},
                    "color": {"type": "string", "enum": list(NOTE_COLOR_CHOICES)},
                    "band": {
                        "type": "string",
                        "description": _require(text, "keep_note.band"),
                    },
                    "priority": {"type": "string", "enum": ["high", "normal", "low"]},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        ),
        (
            "update_household_context",
            _require(text, "update_household_context"),
            {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "enum": list(CONTEXT_LANES)},
                    "text": {"type": "string"},
                    "mode": {"type": "string", "enum": ["append", "replace"]},
                    "expected_updated_at": {"type": ["string", "null"]},
                },
                "required": ["section", "text"],
                "additionalProperties": False,
            },
        ),
        (
            "set_scratch",
            _require(text, "set_scratch"),
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": SCRATCH_LIMIT},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        ),
        (
            "propose_dinners",
            _require(text, "propose_dinners"),
            {
                "type": "object",
                "properties": {
                    "weekStart": {"type": "string"},
                    "notes": {"type": "string"},
                    "expected_updated_at": {"type": ["string", "null"]},
                    "days": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "day": {"type": "string", "enum": list(WEEKDAYS)},
                                "recipe": {"type": ["string", "null"]},
                                "title": {"type": "string"},
                                "ingredients": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["day", "title"],
                        },
                    },
                },
                "required": ["weekStart", "days"],
            },
        ),
    ]

    expected_keys = set(_CORE_TOOL_NAMES)
    for key in _RECIPE_FIELD_TEXT:
        expected_keys.add("fields." + key)
    expected_keys.update(
        {
            "fields.note.original",
            "fields.note.band",
            "fields.expected_updated_at",
            "search_cookbook.query",
            "search_cookbook.full",
            "analyze_cookbook.list",
            "keep_note.band",
        }
    )
    for key in _FILTER_FIELD_TEXT:
        expected_keys.add("filters." + key)

    orphans = sorted(set(text) - expected_keys)
    if orphans:
        raise ValueError("Orphan tool text keys: " + ", ".join(orphans))
    missing = sorted(expected_keys - set(text))
    if missing:
        raise ValueError("Missing tool text keys: " + ", ".join(missing))

    return specs


def __getattr__(name: str):
    # Lazy stand-ins for callers that still import the old module constants.
    if name == "TOOL_SPECS":
        return tool_specs()
    if name == "CATALOG_FILTER_PROPERTIES":
        return _catalog_filters(load_tool_text())
    if name == "SEARCH_COOKBOOK_SCHEMA":
        return _search_cookbook_schema(load_tool_text())
    if name == "ANALYZE_COOKBOOK_SCHEMA":
        return _analyze_cookbook_schema(load_tool_text())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


TOOL_LABELS = {
    "add_recipe": "Added a recipe",
    "edit_recipe": "Edited a recipe",
    "append_recipe_context": "Appended recipe context",
    "delete_recipe": "Deleted a cookbook card",
    "search_cookbook": "Looked in the cookbook",
    "analyze_cookbook": "Reviewed the catalog",
    "search_history": "Searched the kitchen history",
    "read_chat_history": "Read an earlier chat",
    "keep_note": "Kept a note",
    "update_household_context": "Updated household context",
    "set_scratch": "Updated private scratch",
    "read_notes": "Read the notes",
    "analyze_notes": "Checked current notes",
    "search_notes": "Searched the notes",
    "edit_note": "Edited a note",
    "delete_note": "Deleted a note",
    "propose_dinners": "Saved dinners",
    "attach_recipe_photos": "Attached recipe photos",
}

TOOL_FAILURE_LABELS = {
    "propose_dinners": "Couldn't save dinners",
}
