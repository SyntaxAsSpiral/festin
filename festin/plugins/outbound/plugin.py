"""Outbound plugin. send_list registers only while Cloud agents is on."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from festin.chat.persona import load_blocks
from festin.plugins.outbound import webhooks

PLUGIN_ID = "outbound"
PLUGIN_NAME = "Cloud agents"
_TOOLS_YAML = Path(__file__).resolve().parent / "tools.yaml"
_OUTBOUND_TOOL_KEYS = ("send_list",)


def tool_text() -> dict[str, str]:
    blocks = load_blocks(_TOOLS_YAML)
    orphans = sorted(set(blocks) - set(_OUTBOUND_TOOL_KEYS))
    if orphans:
        raise ValueError("Orphan outbound tool text keys: " + ", ".join(orphans))
    missing = sorted(set(_OUTBOUND_TOOL_KEYS) - set(blocks))
    if missing:
        raise ValueError("Missing outbound tool text keys: " + ", ".join(missing))
    return blocks


class OutboundPlugin:
    id = PLUGIN_ID
    name = PLUGIN_NAME

    def settings_schema(self) -> list[dict]:
        return [
            {
                "key": "defaultAgent",
                "type": "string",
                "default": "",
                "label": "Default agent",
                "help": "Used when send_list omits agent.",
            },
            {
                "key": "destinations",
                "type": "agents",
                "default": [],
                "label": "Destinations",
                "help": (
                    "Named HTTP(S) webhooks. Auth env is a variable name; the secret "
                    "stays in the kitchen environment."
                ),
            },
        ]

    def register(self, registry) -> None:
        text = tool_text()
        registry.register_tool(
            "send_list",
            text["send_list"],
            {
                "type": "object",
                "properties": {
                    "list_name": {"type": "string", "minLength": 1},
                    "agent": {"type": "string", "minLength": 1},
                },
                "required": ["list_name"],
                "additionalProperties": False,
            },
            _send_list,
            label="Sent a list",
        )

    def actions(self) -> dict:
        return {
            "destinations": _action_destinations,
        }

    def feed(self) -> dict:
        return {"ok": True}


def _send_list(args, ctx):
    return webhooks.send_list(ctx.conn, args or {})


def _action_destinations(conn, body, *, data_dir, now=None):
    stamp = _stamp(now)
    return webhooks.save_destination(conn, body or {}, stamp=stamp)


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


PLUGIN = OutboundPlugin()
