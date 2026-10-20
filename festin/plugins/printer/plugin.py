"""Printer plugin. Tools register on the shared ToolRegistry only while it is on."""

from __future__ import annotations

from pathlib import Path

from festin.chat.persona import fill_placeholders, load_blocks
from festin.plugins.printer import printing, slips

PLUGIN_ID = "printer"
PLUGIN_NAME = "Thermal printer"
_TOOLS_YAML = Path(__file__).resolve().parent / "tools.yaml"
_PRINTER_TOOL_KEYS = (
    "prepare_slip",
    "print_slip",
    "prepare_slip.note_id",
    "prepare_slip.band",
    "prepare_slip.plates",
    "prepare_slip.quote",
)


def tool_text() -> dict[str, str]:
    """Load printer tool prose; placeholders filled from the live catalogs."""
    blocks = load_blocks(_TOOLS_YAML)
    values = {
        "slip_sentence": slips.SLIP_SENTENCE,
        "plate_listing": printing.plate_tool_listing(),
        "band_listing": printing.band_listing(),
    }
    filled = {key: fill_placeholders(body, values) for key, body in blocks.items()}
    orphans = sorted(set(filled) - set(_PRINTER_TOOL_KEYS))
    if orphans:
        raise ValueError("Orphan printer tool text keys: " + ", ".join(orphans))
    missing = sorted(set(_PRINTER_TOOL_KEYS) - set(filled))
    if missing:
        raise ValueError("Missing printer tool text keys: " + ", ".join(missing))
    return filled


class PrinterPlugin:
    id = PLUGIN_ID
    name = PLUGIN_NAME

    def settings_schema(self) -> list[dict]:
        bands = printing.band_catalog()["bands"]
        command_on = slips.print_command_configured()
        mode_enum = ["", "receiver"]
        mode_choices = [
            {"id": "", "description": "Off"},
            {"id": "receiver", "description": "Print receiver"},
        ]
        mode_help = (
            "How Festin hands a finished PNG slip to your printer. "
            "Off never attempts a print. Print receiver POSTs the image to a "
            "small HTTP service (see docs/print-receiver.md)."
        )
        if command_on:
            mode_enum.append("command")
            mode_choices.append({"id": "command", "description": "Print command"})
            mode_help += (
                " Print command runs the host's FESTIN_PRINT_COMMAND (set on the "
                "server, not editable here), with {file} replaced by the PNG path."
            )
        else:
            mode_help += (
                " Print command appears here only when the host sets FESTIN_PRINT_COMMAND."
            )
        return [
            {
                "key": "deliveryMode",
                "type": "string",
                "default": "",
                "label": "Delivery",
                "help": mode_help,
                "enum": mode_enum,
                "choices": mode_choices,
            },
            {
                "key": "receiverUrl",
                "type": "string",
                "default": "",
                "label": "Print receiver URL",
                "help": (
                    "Used when Delivery is Print receiver. Base URL only — Festin POSTs "
                    "to <url>/print. Example: http://127.0.0.1:8766"
                ),
            },
            {
                "key": "token",
                "type": "string",
                "default": "",
                "label": "Print receiver token",
                "secret": True,
                "help": "Bearer token the receiver expects. Used only in Print receiver mode.",
            },
            {
                "key": "band",
                "type": "string",
                "default": printing.BABETTE_BAND,
                "label": "Band art",
                "help": (
                    "Babette's pick chooses recipe bands by category and note bands from "
                    "the note or this week's pantry plate. A named band uses that art on "
                    "every recipe and note slip. Dinner slips keep their own weekly plates "
                    "either way."
                ),
                "enum": [printing.BABETTE_BAND] + [row["id"] for row in bands],
                "choices": [
                    {
                        "id": printing.BABETTE_BAND,
                        "description": "Babette's pick",
                    },
                    *[
                        {
                            "id": row["id"],
                            "file": row["file"],
                            "description": row["description"],
                        }
                        for row in bands
                    ],
                ],
            },
            {
                "key": "weeklyPick",
                "type": "boolean",
                "default": False,
                "label": "Babette's weekly pick",
                "help": (
                    "One model call a week to choose the dinner slip's art and "
                    "closing quote. Off uses rotation art and the default quote."
                ),
            },
        ]

    def register(self, registry) -> None:
        text = tool_text()
        registry.register_tool(
            "prepare_slip",
            text["prepare_slip"],
            {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["plan", "recipe", "note"]},
                    "week_start": {"type": "string"},
                    "recipe_id": {"type": "string"},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "note_id": {
                        "type": "string",
                        "description": text["prepare_slip.note_id"],
                    },
                    "band": printing.band_property(text["prepare_slip.band"]),
                    "plates": printing.plates_property(text["prepare_slip.plates"]),
                    "quote": {
                        "type": "string",
                        "description": text["prepare_slip.quote"],
                    },
                },
            },
            _prepare,
            label="Prepared a slip",
        )
        registry.register_tool(
            "print_slip",
            text["print_slip"],
            {
                "type": "object",
                "properties": {"slip_id": {"type": "string"}},
                "required": ["slip_id"],
            },
            _print,
            label="Sent to the printer",
        )

    def actions(self) -> dict:
        return {
            "prepare": slips.action_prepare,
            "print": slips.action_print,
            "print-dinner": slips.action_print_dinner,
            "print-recipe": slips.action_print_recipe,
            "test-slip": slips.action_test_slip,
        }

    def feed(self) -> dict:
        catalog = printing.band_catalog()
        return {
            "bands": catalog["bands"],
            "categories": catalog["categories"],
            "defaultBand": catalog["default"],
            "plates": printing.plate_catalog(),
        }


def _prepare(args, ctx):
    return slips.prepare_slip(ctx.conn, args or {}, data_dir=ctx.data_dir, chat_id=ctx.chat_id)


def _print(args, ctx):
    slip_id = (args or {}).get("slip_id")
    return slips.print_slip(ctx.conn, slip_id, data_dir=ctx.data_dir)


PLUGIN = PrinterPlugin()
