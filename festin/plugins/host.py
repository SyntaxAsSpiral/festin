"""Plugin host. Each plugin is off until a device turns it on.

Settings live in plugin_settings. Tools land on festin.chat.registry.ToolRegistry.
HTTP actions are /api/plugins/<id>/<action>. Feeds are /api/plugins/<id>/feed.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

from festin.chat.core_tools import register_core_tools
from festin.chat.registry import ToolRegistry
from festin.errors import NotFound
from festin.plugins.outbound.plugin import PLUGIN as OUTBOUND
from festin.plugins.printer.plugin import PLUGIN as PRINTER
from festin.plugins.tattva.plugin import PLUGIN as TATTVA

PLUGINS = (PRINTER, TATTVA, OUTBOUND)
_BY_ID = {plugin.id: plugin for plugin in PLUGINS}


def list_plugins(conn: sqlite3.Connection) -> list[dict]:
    return [_public(conn, plugin) for plugin in PLUGINS]


def get_plugin(conn: sqlite3.Connection, plugin_id: str) -> dict:
    return _public(conn, _require(plugin_id))


def update_plugin(conn: sqlite3.Connection, plugin_id: str, body: dict, *, now: datetime | None = None) -> dict:
    plugin = _require(plugin_id)
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    unknown = set(body) - {"enabled", "settings"}
    if unknown:
        raise ValueError("Unknown plugin field: " + sorted(unknown)[0])
    current = _stored(conn, plugin)
    enabled = current["enabled"]
    settings = dict(current["settings"])
    if "enabled" in body:
        if type(body["enabled"]) is not bool:
            raise ValueError("enabled must be true or false")
        enabled = body["enabled"]
    if "settings" in body:
        settings = _merge_settings(plugin, settings, body["settings"])
    when = _stamp(now)
    conn.execute(
        """
        INSERT INTO plugin_settings (plugin_id, enabled, settings_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (plugin_id) DO UPDATE SET
            enabled = excluded.enabled,
            settings_json = excluded.settings_json,
            updated_at = excluded.updated_at
        """,
        (plugin.id, 1 if enabled else 0, json.dumps(settings, ensure_ascii=False), when),
    )
    conn.commit()
    return _public(conn, plugin)


def feed(plugin_id: str) -> dict:
    plugin = _require(plugin_id)
    return plugin.feed()


def enabled(conn: sqlite3.Connection, plugin_id: str) -> bool:
    plugin = _require(plugin_id)
    return _stored(conn, plugin)["enabled"]


def build_registry(conn: sqlite3.Connection) -> ToolRegistry:
    """Core tools, plus each enabled plugin's tools and opening contributors."""
    registry = register_core_tools(ToolRegistry())
    for plugin in PLUGINS:
        if _stored(conn, plugin)["enabled"]:
            plugin.register(registry)
    return registry


def call_action(conn, plugin_id: str, action: str, body: dict, *, data_dir, now=None):
    plugin = _require(plugin_id)
    if not _stored(conn, plugin)["enabled"]:
        raise NotFound("That plugin is off.")
    handler = plugin.actions().get(action)
    if handler is None:
        raise NotFound("Not found")
    return handler(conn, body, data_dir=data_dir, now=now)


def parse_plugin_path(path: str) -> tuple[str, str]:
    prefix = "/api/plugins/"
    if not path.startswith(prefix):
        raise NotFound("Not found")
    rest = path[len(prefix) :]
    plugin_id, sep, action = rest.partition("/")
    if not plugin_id or "/" in action or (sep and not action):
        raise NotFound("Not found")
    _require(plugin_id)
    return plugin_id, action


def _require(plugin_id: str):
    plugin = _BY_ID.get(plugin_id)
    if plugin is None:
        raise NotFound("Unknown plugin")
    return plugin


# PUT may send these in place of a secret; they mean "keep the stored value".
_SECRET_PLACEHOLDERS = frozenset({"", "••••", "<set>"})


def _public(conn, plugin) -> dict:
    stored = _stored(conn, plugin)
    return {
        "id": plugin.id,
        "name": plugin.name,
        "enabled": stored["enabled"],
        "settings": _public_settings(plugin, stored["settings"]),
        "schema": plugin.settings_schema(),
    }


def _public_settings(plugin, settings: dict) -> dict:
    """Public settings never include secret values — only a <key>Set flag."""
    from festin.plugins.printer import slips as printer_slips

    out = {}
    for field in plugin.settings_schema():
        key = field["key"]
        if field.get("secret"):
            out[key + "Set"] = bool(str(settings.get(key) or "").strip())
            continue
        if key == "deliveryMode" and plugin.id == "printer":
            mode = printer_slips.resolve_delivery_mode(settings)
            if mode == "command" and not printer_slips.print_command_configured():
                mode = ""
            out[key] = mode
            continue
        out[key] = settings.get(key, field.get("default"))
    return out


def _stored(conn, plugin) -> dict:
    defaults = _defaults(plugin)
    row = conn.execute(
        "SELECT enabled, settings_json FROM plugin_settings WHERE plugin_id = ?",
        (plugin.id,),
    ).fetchone()
    if row is None:
        return {"enabled": False, "settings": defaults}
    raw = json.loads(row["settings_json"] or "{}")
    if not isinstance(raw, dict):
        raw = {}
    settings = dict(defaults)
    settings.update({key: raw[key] for key in defaults if key in raw})
    return {"enabled": bool(row["enabled"]), "settings": settings}


def _defaults(plugin) -> dict:
    return {field["key"]: field["default"] for field in plugin.settings_schema()}


def _merge_settings(plugin, current: dict, incoming) -> dict:
    if not isinstance(incoming, dict):
        raise ValueError("settings must be an object")
    schema = {field["key"]: field for field in plugin.settings_schema()}
    unknown = set(incoming) - set(schema)
    if unknown:
        raise ValueError("Unknown plugin setting: " + sorted(unknown)[0])
    merged = dict(current)
    for key, value in incoming.items():
        field = schema[key]
        if field.get("secret") and _secret_keep(value):
            continue
        merged[key] = _clean_setting(field, value)
    return merged


def _secret_keep(value) -> bool:
    """True when the client omitted a real secret (empty or a mask placeholder)."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value in _SECRET_PLACEHOLDERS


def _clean_setting(field: dict, value):
    if field["type"] == "boolean":
        if type(value) is not bool:
            raise ValueError(field["key"] + " must be true or false")
        return value
    if field["type"] == "agents":
        from festin.plugins.outbound.webhooks import clean_destinations

        return clean_destinations(value)
    if field["type"] == "string":
        if not isinstance(value, str):
            raise ValueError(field["key"] + " must be text")
        if field["key"] == "receiverUrl":
            return _clean_url(value, label="Print receiver URL")
        if field["key"] == "sideriodUrl":
            return _clean_url(value, label="Sideriod URL")
        if field["key"] == "dinnerHour":
            from festin.plugins.tattva.compute import clean_dinner_hour

            return clean_dinner_hour(value)
        if field.get("secret") or field["key"] == "token":
            if len(value) > 500:
                raise ValueError(field["key"] + " is too long")
            return value
        if field["key"] == "defaultAgent" and len(value) > 80:
            raise ValueError("defaultAgent is too long")
        if "enum" in field and value not in field["enum"]:
            if field["key"] == "band":
                raise ValueError("Unknown band art: " + value)
            if field["key"] == "deliveryMode":
                raise ValueError("Unknown delivery mode: " + value)
            raise ValueError("Unknown " + field["key"] + ": " + value)
        return value
    raise ValueError("Unknown plugin setting: " + field["key"])


def _clean_url(value: str, *, label: str = "URL") -> str:
    text = value.strip()
    if not text:
        return ""
    if len(text) > 300 or any(ch.isspace() for ch in text):
        raise ValueError(label + " must be an http(s) URL.")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(label + " must be an http(s) URL.")
    return text


def _stamp(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
