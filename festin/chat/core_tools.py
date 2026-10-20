"""Wire the eighteen core kitchen tools into a ToolRegistry."""

from __future__ import annotations

from festin import household as household_mod
from festin import scratch as scratch_mod
from festin.chat import schemas
from festin.chat.registry import ToolRegistry
from festin.chat import tools_history, tools_notes, tools_plans, tools_recipes

_HANDLERS = {
    "search_cookbook": tools_recipes.search_cookbook,
    "analyze_cookbook": tools_recipes.analyze_cookbook,
    "add_recipe": tools_recipes.add_recipe,
    "edit_recipe": tools_recipes.edit_recipe,
    "append_recipe_context": tools_recipes.append_recipe_context,
    "delete_recipe": tools_recipes.delete_recipe,
    "attach_recipe_photos": tools_recipes.attach_recipe_photos,
    "propose_dinners": tools_plans.propose_dinners,
    "search_notes": tools_notes.search_notes,
    "analyze_notes": tools_notes.analyze_notes,
    "read_notes": tools_notes.read_notes,
    "edit_note": tools_notes.edit_note,
    "delete_note": tools_notes.delete_note,
    "keep_note": tools_notes.keep_note,
    "update_household_context": household_mod.update_household_context,
    "set_scratch": scratch_mod.set_scratch,
    "search_history": tools_history.search_history,
    "read_chat_history": tools_history.read_chat_history,
}


def register_core_tools(registry: ToolRegistry) -> ToolRegistry:
    for name, description, parameters in schemas.tool_specs():
        registry.register_tool(
            name,
            description,
            parameters,
            _HANDLERS[name],
            label=schemas.TOOL_LABELS.get(name),
            failure_label=schemas.TOOL_FAILURE_LABELS.get(name),
        )
    return registry


def build_core_registry() -> ToolRegistry:
    """Fresh registry with the eighteen core tools. Used by the turn engine."""
    return register_core_tools(ToolRegistry())
