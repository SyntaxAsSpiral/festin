"""Printer plugin. Tools register on the shared ToolRegistry only while it is on."""

from __future__ import annotations

from festin.plugins.printer import printing, slips

PLUGIN_ID = "printer"
PLUGIN_NAME = "Thermal printer"

_PREPARE = (
    "Prepare a PNG preview of a dinner plan, catalog recipe, praxis card, or note. "
    "Does not print. Returns rendered_text for content checks with text-only models. "
    "For recipes and praxis, pass recipe_id; kind=recipe is inferred if omitted. "
    "Recipe and note band art follows Settings: Babette's pick uses the card category "
    "(and note band rules); a named band uses that band for every recipe and note slip. "
    "Dinner slips keep their own weekly plates either way. For plans pass kind=plan and "
    "week_start; matching draft takes precedence over saved plan. When the week has no "
    "plates stored, pass plates {top,bottom,header,pantry} chosen for the season and "
    "dinners. Pass quote for a short French closing line on the dinner slip (printed "
    "only; default Pour les dames de la maison.). For notes pass kind=note with the "
    "title and the text to print; both are "
    "required. To print a saved note, read it and write a print-friendly title and text "
    "yourself. Saved notes are not written for reading and do not need to be. You may "
    "use **bold** sparingly. Pass note_id only to take that note’s band when you omit "
    "band. Inspect the supplied preview before printing. "
    + slips.SLIP_SENTENCE
)

_PRINT = (
    "Print ONE copy of a prepared slip on the kitchen printer. Only call when the user "
    "requested physical printing, after checking prepare_slip preview (rendered_text "
    "for text-only models). Repeated calls for the same slip will not print again. "
    "If status is uncertain, report it and do not create a replacement automatically. "
    + slips.SLIP_SENTENCE
)


class PrinterPlugin:
    id = PLUGIN_ID
    name = PLUGIN_NAME

    def settings_schema(self) -> list[dict]:
        bands = printing.band_catalog()["bands"]
        return [
            {
                "key": "receiverUrl",
                "type": "string",
                "default": "",
                "label": "Print receiver URL",
            },
            {
                "key": "token",
                "type": "string",
                "default": "",
                "label": "Print receiver token",
                "secret": True,
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
        registry.register_tool(
            "prepare_slip",
            _PREPARE,
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
                        "description": (
                            "Saved note id. Supplies only the default band when band is omitted. "
                            "Read the note and write the title and text yourself."
                        ),
                    },
                    "band": printing.band_property(
                        "Note slips only. Omit to use a saved note’s band, or this week’s pantry plate."
                    ),
                    "plates": printing.plates_property(),
                    "quote": {
                        "type": "string",
                        "description": (
                            "Dinner-slip closing line for kind=plan. Short French motto "
                            "or sign-off, printed only. Omit to keep a stored quote, or "
                            "the default Pour les dames de la maison."
                        ),
                    },
                },
            },
            _prepare,
            label="Prepared a slip",
        )
        registry.register_tool(
            "print_slip",
            _PRINT,
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
