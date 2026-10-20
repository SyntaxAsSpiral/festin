"""Tool prose lives in YAML beside the persona; structure stays in schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from festin.chat.core_tools import build_core_registry
from festin.chat.persona import fill_placeholders, load_blocks, load_persona
from festin.chat.schemas import (
    DEFAULT_TOOLS,
    _CORE_TOOL_NAMES,
    _FILTER_FIELD_TEXT,
    _RECIPE_FIELD_TEXT,
    load_tool_text,
    placeholder_values,
    tool_specs,
)
from festin.plugins.outbound.plugin import tool_text as outbound_tool_text
from festin.plugins.printer.plugin import tool_text as printer_tool_text

BEFORE = Path(__file__).resolve().parent / "fixtures" / "tool_specs_before.json"

# Deliberate wording fixes applied while moving prose into tools.yaml.
EXPECTED_DIFFS = {
    "search_cookbook": {
        "kind is recipe or praxis.": (
            "kind is formule or praxis (recipe aliases formule for one release)."
        ),
    },
    "edit_recipe": {
        "existing cookbook card (recipe or praxis).": (
            "existing cookbook card (formule or praxis)."
        ),
    },
    "append_recipe_context": {
        "a recipe or praxis card context": "a formule or praxis card context",
    },
    "delete_recipe": {
        "one recipe or praxis card": "one formule or praxis card",
    },
}


def _apply_expected(before_desc: str, name: str) -> str:
    text = before_desc
    for old, new in EXPECTED_DIFFS.get(name, {}).items():
        text = text.replace(old, new)
    return text


def test_load_blocks_persona_and_tools_share_parser():
    persona = load_persona()
    assert "system_prompt" in persona
    assert "We are Babette" in persona["system_prompt"]
    tools = load_blocks(DEFAULT_TOOLS)
    assert "search_cookbook" in tools
    assert tools["search_cookbook"].startswith("Find cookbook cards.")


def test_placeholders_resolve_and_unknown_raises():
    values = placeholder_values()
    filled = fill_placeholders(
        "plates {plate_slugs}; cap {open_note_cap}; days {dinner_history_days}; "
        "ctx {context_cap}; house {household_limit}; pref {preferences_limit}; "
        "rest {restrictions_limit}",
        values,
    )
    assert str(values["open_note_cap"]) in filled
    assert values["plate_slugs"] in filled
    assert "1,000" in filled
    with pytest.raises(ValueError, match="Unknown or unfilled placeholder"):
        fill_placeholders("hello {no_such_thing}", values)


def test_curly_object_shapes_are_not_placeholders():
    # prepare_slip mentions plates {top,bottom,header,pantry}; that is shape prose.
    text = fill_placeholders(
        "plates {top,bottom,header,pantry} from {plate_slugs}",
        {"plate_slugs": "breads"},
    )
    assert text == "plates {top,bottom,header,pantry} from breads"


def test_every_core_tool_and_field_has_text_no_orphans():
    text = load_tool_text()
    for name in _CORE_TOOL_NAMES:
        assert name in text and text[name].strip()
    for key in _RECIPE_FIELD_TEXT:
        assert text["fields." + key].strip()
    for key in _FILTER_FIELD_TEXT:
        assert text["filters." + key].strip()
    assert text["fields.note.original"].strip()
    assert text["fields.note.band"].strip()
    assert text["fields.expected_updated_at"].strip()
    assert text["search_cookbook.query"].strip()
    assert text["search_cookbook.full"].strip()
    assert text["analyze_cookbook.list"].strip()
    assert text["keep_note.band"].strip()
    # tool_specs itself rejects orphans / missing keys
    specs = tool_specs()
    assert [name for name, _d, _p in specs] == list(_CORE_TOOL_NAMES)


def test_assembled_tools_match_before_except_listed_fixes():
    assert BEFORE.is_file(), "before-snapshot missing; regenerate from main schemas"
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    after = [
        {"name": name, "description": desc, "parameters": params}
        for name, desc, params in tool_specs()
    ]
    assert [row["name"] for row in before] == [row["name"] for row in after]
    for old, new in zip(before, after):
        name = old["name"]
        expected_desc = _apply_expected(old["description"], name)
        assert new["description"] == expected_desc, name
        assert new["parameters"] == old["parameters"], name


def test_registry_openai_tools_use_yaml_prose():
    tools = build_core_registry().openai_tools()
    by_name = {item["function"]["name"]: item["function"] for item in tools}
    assert "formule or praxis (recipe aliases formule for one release)" in by_name[
        "search_cookbook"
    ]["description"]
    assert "kind is recipe or praxis" not in by_name["search_cookbook"]["description"]
    assert by_name["keep_note"]["description"].count("25") >= 1


def test_printer_and_outbound_tool_yaml():
    printer = printer_tool_text()
    assert "Prepare a PNG preview" in printer["prepare_slip"]
    assert "Slips are ephemeral" in printer["prepare_slip"]
    assert "scroll:" in printer["prepare_slip.band"] or "bay:" in printer["prepare_slip.band"]
    assert "top:" in printer["prepare_slip.plates"]
    outbound = outbound_tool_text()
    assert "Send one named notebook list" in outbound["send_list"]


def test_persona_agrees_with_tool_card_link_and_cook():
    prompt = load_persona()["system_prompt"]
    search = load_tool_text()["search_cookbook"]
    edit = load_tool_text()["edit_recipe"]
    assert "[Title](CBK-####)" in prompt
    assert "[Title](CBK-####)" in search
    assert "cooked: true" in prompt or "{cooked: true}" in prompt
    assert "{cooked: true}" in edit or "cooked true" in edit
