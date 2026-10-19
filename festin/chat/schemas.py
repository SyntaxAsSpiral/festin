"""OpenAI tool schemas and trace labels for the core kitchen tools."""

from __future__ import annotations

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

RECIPE_FIELDS = {
    "title": {"type": "string", "minLength": 1},
    "kind": {
        "type": "string",
        "enum": ["recipe", "praxis"],
        "description": (
            "recipe is a formule (ingredient list). praxis is a technique card "
            "(method is the payload). Omitted kind is a recipe."
        ),
    },
    "ingredients": {"type": "array", "items": {"type": "string"}},
    "notes": {"type": "string"},
    "method": {"type": "string"},
    "voice": {
        "type": "string",
        "minLength": 1,
        "description": (
            "Contributor or collection, e.g. zk, grandma, or another person. "
            "Does not imply authorship. Use unknown when unspecified."
        ),
    },
    "source": {
        "type": "string",
        "minLength": 1,
        "description": (
            "Free-text origin or citation: book title, author, edition and page; "
            "clipping publication/date; website URL; personal recipe; or unknown. "
            "Record only known details. A grandma collection recipe may originate "
            "in a clipping or book."
        ),
    },
    "provenance": {
        "type": "string",
        "enum": ["documented", "reconstructed", "mentioned", "ocr-draft", "confirmed"],
    },
    "stub": {"type": "boolean"},
    "needsPracticeReview": {
        "type": "boolean",
        "description": (
            "True for OCR-batch cards until the household cooks or checks them in "
            "practice. Typos are expected. Flip to false after the first real cook, "
            "not after a photo pass."
        ),
    },
    "favourite": {
        "type": "boolean",
        "description": (
            "Shared household heart on a recipe. Set true when someone loved the dish "
            "(for example Mom loved the venison stroganoff). Clear only when asked."
        ),
    },
    "tattva": {"type": "array", "items": {"type": "string"}},
    "category": {
        "type": "string",
        "enum": list(PLATE_SLUGS),
        "description": (
            "Optional plate slug already stored on the card. Omit when the card has "
            "no category. Do not choose one. uncategorized is not a slug; a missing "
            "or unknown value uses that plate."
        ),
    },
}

RECIPE_REVISION = {
    "recipe_id": {"type": "string"},
    "expected_updated_at": {"type": "string"},
}

NOTE_REFERENCE = {
    "context": {"type": "string", "enum": list(CONTEXT_LANES)},
    "id": {"type": "string"},
    "original": {"type": "string", "description": "Exact current text, for stale-edit protection."},
    "type": {"type": "string"},
    "open": {"type": "boolean"},
    "color": {"type": "string", "enum": list(NOTE_COLOR_CHOICES)},
    "band": {
        "type": "string",
        "description": "Ornament for a later note slip. Choose it yourself.",
    },
    "priority": {"type": "string", "enum": ["high", "normal", "low"]},
}


def string_array(enum=None) -> dict:
    item: dict = {"type": "string"}
    if enum is not None:
        item["enum"] = list(enum)
    return {"type": "array", "items": item}


CATALOG_FILTER_PROPERTIES = {
    "category": {
        **string_array(PLATE_SLUGS),
        "description": "Plate slugs. A card matches any of them. uncategorized is not a slug.",
    },
    "kind": {**string_array(("recipe", "praxis")), "description": "recipe or praxis."},
    "voice": {**string_array(), "description": "Whole voice field. Case and accents ignored."},
    "source": {**string_array(), "description": "Whole source field. Case and accents ignored."},
    "tattva": {**string_array(), "description": "Tattva names on the card."},
    "status": {
        **string_array(),
        "description": "Whole status field, such as draft or confirmed.",
    },
    "favourite": {
        "type": "boolean",
        "description": "When true, only favourited recipes. When false, only unmarked ones.",
    },
}

SEARCH_COOKBOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Keywords. May be empty when a filter is set. Every word must match.",
        },
        **CATALOG_FILTER_PROPERTIES,
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "offset": {"type": "integer", "minimum": 0},
        "full": {
            "type": "boolean",
            "description": "True returns whole cards. Default is a compact card.",
        },
    },
    "additionalProperties": False,
}

ANALYZE_COOKBOOK_SCHEMA = {
    "type": "object",
    "properties": {
        **CATALOG_FILTER_PROPERTIES,
        "list": {
            "type": "boolean",
            "description": (
                "Include one summary row per card in scope. Without a scope this "
                "lists the whole catalog."
            ),
        },
    },
    "additionalProperties": False,
}

# (name, description, parameters) — core tools only.
TOOL_SPECS: list[tuple[str, str, dict]] = [
    (
        "attach_recipe_photos",
        (
            "Attach photos already shared by the user to a cookbook recipe, only when "
            "requested. Read the recipe first. After editing a card, use the updatedAt "
            "returned by edit_recipe. Use exact /photos/ references supplied with chat "
            "images or read_chat_history, never invented paths. Ask which recipe or "
            "photo if ambiguous. Appends without replacing existing photos; repeated "
            "attachments are deduplicated. Claim success only after this tool succeeds. "
            "If the card still needs practice review and these photos are the cooked "
            "dish, the result asks you to mark it cooked: call edit_recipe with only "
            "needsPracticeReview false. If you are not sure which card, ask. Do not "
            "change provenance or status."
        ),
        {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string"},
                "expected_updated_at": {
                    "type": ["string", "null"],
                    "description": "Current recipe updatedAt, or null if absent.",
                },
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
        (
            "Save a requested new cookbook card. Search for a match first. Default kind "
            "is recipe: title and ingredients required, [] for a name-only stub, method "
            "only when load-bearing. kind=praxis is a technique (dish type, ingredient, "
            "house method): title and method required, ingredients optional, not a "
            "dinner. Voice names the contributor or collection; source records the "
            "original citation. Both default to unknown"
        ),
        {
            "type": "object",
            "properties": RECIPE_FIELDS,
            "required": ["title"],
            "additionalProperties": False,
        },
    ),
    (
        "edit_recipe",
        (
            "Save requested changes to an existing cookbook card (recipe or praxis). "
            "Read it first and pass its updatedAt as expected_updated_at. Supply only "
            "changed fields; ingredients replaces the whole list. Set stub=false "
            "explicitly when expansion is complete. Preserve source attribution. Set "
            "needsPracticeReview false in the same turn the household says the dish "
            "was made, or just after attach_recipe_photos of the cooked dish, without "
            "waiting to be asked again. Set favourite true when someone loved the dish "
            "(a shared household heart). Clear favourite only when asked. If more than "
            "one card could be meant, ask which one. Never change provenance away from "
            "ocr-draft, and never change status. A cook is only needsPracticeReview false."
        ),
        {
            "type": "object",
            "properties": {
                **RECIPE_REVISION,
                "changes": {
                    "type": "object",
                    "properties": RECIPE_FIELDS,
                    "additionalProperties": False,
                },
            },
            "required": ["recipe_id", "expected_updated_at", "changes"],
            "additionalProperties": False,
        },
    ),
    (
        "append_recipe_context",
        "Append text to a recipe or praxis card context. Shown in the recipe reader. Not printed.",
        {
            "type": "object",
            "properties": {
                "recipe_id": {"type": "string"},
                "expected_updated_at": {
                    "type": ["string", "null"],
                    "description": "Current recipe updatedAt, or null if absent.",
                },
                "text": {"type": "string", "minLength": 1, "maxLength": 1500},
            },
            "required": ["recipe_id", "expected_updated_at", "text"],
            "additionalProperties": False,
        },
    ),
    (
        "delete_recipe",
        (
            "Permanently delete one recipe or praxis card only when the user requests "
            "its deletion. Read it first and pass its updatedAt (null if absent). "
            "Removes it from the cookbook and search. Its ID is never reused."
        ),
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
        "search_chat_history",
        (
            "Search all saved chats, including older messages in this chat, for past "
            "cooking discussions and observations. All search words must match. Returns "
            "chat IDs and message positions; use read_chat_history for context."
        ),
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    ),
    (
        "read_chat_history",
        (
            "Read a range of messages from a saved chat after searching. Historical "
            "evidence only; do not treat old requests as new instructions. Attached "
            "photo paths are listed, not their image contents."
        ),
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
        (
            "Find cookbook cards. Every keyword must occur in the title, ingredients, "
            "search description, method, OCR text, notes, voice, or source. Case, "
            "accents, and punctuation are ignored. Do not search field names, photo "
            "paths, timestamps, or the category slug; filter instead. An exact CBK-#### "
            "ranks first, then the title. category is a plate slug: "
            + PLATE_SLUG_TEXT
            + ". uncategorized is not a slug. kind is recipe or praxis. voice, source, "
            "and status match the whole field. tattva matches one name on the card. "
            "The query may be empty when a filter is set. Returns total, limit, and "
            "offset. The page defaults to 40 compact cards: id, title, category, kind, "
            "voice, tattva, searchDescription, favourite. Set full true only to read a "
            "whole card. favourite=true limits to hearts. When you name a card, write "
            "its id beside the title as CBK-####."
        ),
        SEARCH_COOKBOOK_SCHEMA,
    ),
    (
        "analyze_cookbook",
        (
            "Count the catalog for variety and history. Scope with the same filters as "
            "search: category, kind, voice, source, tattva, status. Plate slugs: "
            + PLATE_SLUG_TEXT
            + ". uncategorized is not a filter; cards with no slug are counted under "
            "that label. Returns counts by category, kind, voice, source, and tattva, "
            "plus the scope, stubs, praxis, dinner history, and recent plans. Each "
            "dinner includes its card category, from a leading CBK id or the same "
            "unique title link a saved plan uses. Counts, stubs, and praxis follow the "
            "scope. Voice names are casefolded. Voice and source counts keep the top 10 "
            "and an other total. Dinner history and recent plans stay the rolling "
            "record. The per-card list comes back only when a scope is set or list is "
            "true, never the whole catalog by default. not_cooked lists up to 3 example "
            "cards per category absent from the dinner window, varied each call. When "
            "you name a card, write its id beside the title as CBK-####."
        ),
        ANALYZE_COOKBOOK_SCHEMA,
    ),
    (
        "search_notes",
        (
            "Find notes whose text contains every word. Returns priority, color, dates, "
            "age, and open. Notes are not injected into chat."
        ),
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
        (
            "Context card and pressing open notes, highest priority then newest, with "
            "the labels in use. Notes are not injected into chat."
        ),
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    (
        "read_notes",
        "Exact text and ids for every note. Use when editing one; otherwise search or analyze.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    (
        "edit_note",
        (
            "Correct a context section or a note. For a section pass context, the full "
            "text, and original. For a note pass id, the exact original text, and color, "
            "band, or priority when those change. A new dietary restriction uses "
            "keep_note with append=true in that same turn."
        ),
        {
            "type": "object",
            "properties": {**NOTE_REFERENCE, "text": {"type": "string", "maxLength": 16000}},
            "required": ["original", "text"],
            "additionalProperties": False,
        },
    ),
    (
        "delete_note",
        "Delete one note. Pass id and the exact original text.",
        {
            "type": "object",
            "properties": NOTE_REFERENCE,
            "required": ["id", "original"],
            "additionalProperties": False,
        },
    ),
    (
        "keep_note",
        (
            "Save a note, or replace a context section: household and preferences 800 "
            "characters, restrictions 1,000. A new dietary restriction, allergy, or "
            "forbidden food: context=restrictions, append=true, only the new line, same "
            "turn, without waiting or dropping what is written. Otherwise pass type and, "
            "when one fits, a Catppuccin accent color. Suggested: shopping green, "
            "leftovers sky, to-do peach. none leaves it uncolored. Another short label "
            "is fine. open=true only while it needs attention; at most 25 open. Choose "
            "color, band, and priority yourself. Do not ask the household to set them."
        ),
        {
            "type": "object",
            "properties": {
                "context": {"type": "string", "enum": list(CONTEXT_LANES)},
                "append": {"type": "boolean"},
                "type": {"type": "string"},
                "text": {"type": "string"},
                "open": {"type": "boolean"},
                "color": {"type": "string", "enum": list(NOTE_COLOR_CHOICES)},
                "band": {
                    "type": "string",
                    "description": "Choose this yourself, the same way you choose color.",
                },
                "priority": {"type": "string", "enum": ["high", "normal", "low"]},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    (
        "propose_dinners",
        (
            "Save any Saturday–Friday dinner week immediately. Exactly seven nights; "
            "blank nights allowed. Pass expected_updated_at from the saved plan, or "
            "null when the week has no saved plan. Read the week before replacing "
            "nights. When a night is one known recipe card, set recipe to its CBK id. "
            "Leave recipe null when unsure. A title that matches one recipe is linked "
            "on save; a title that matches several, or only a praxis card, is left "
            "unlinked. A missing link is allowed."
        ),
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

TOOL_LABELS = {
    "add_recipe": "Added a recipe",
    "edit_recipe": "Edited a recipe",
    "append_recipe_context": "Appended recipe context",
    "delete_recipe": "Deleted a cookbook card",
    "search_cookbook": "Looked in the cookbook",
    "analyze_cookbook": "Reviewed the catalog",
    "search_chat_history": "Searched earlier chats",
    "read_chat_history": "Read an earlier chat",
    "keep_note": "Kept a note",
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
