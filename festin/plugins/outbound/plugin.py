"""Outbound plugin. send_list registers only while Cloud agents is on."""

from __future__ import annotations

from datetime import datetime, timezone

from festin.plugins.outbound import webhooks

PLUGIN_ID = "outbound"
PLUGIN_NAME = "Cloud agents"

_SEND = (
    "Send one named notebook list to one configured cloud agent. Call only when the "
    "user explicitly asks to send that list. list_name is the note type, for example "
    'shopping; a trailing " list" is ignored. Omit agent to use the default destination '
    "chosen in Settings. Pass agent only when the user names one. Items are the note "
    "lines. Exactly one destination receives the list, once. Does not purchase, print, "
    "or change the note. Tell the household it was sent, or the plain error, with no "
    "webhook details."
)


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
        registry.register_tool(
            "send_list",
            _SEND,
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
