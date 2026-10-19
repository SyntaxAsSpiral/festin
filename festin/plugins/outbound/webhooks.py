"""Named HTTP(S) destinations and send_list. Auth is an env var name, never a pasted secret."""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from festin import notes as notes_mod

PLUGIN_ID = "outbound"
AUTH_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")

# Tests may replace this with a fake poster: (url, payload, auth_env) -> payload.
list_poster = None


def destination_view(settings: dict) -> dict:
    destinations = []
    for row in settings.get("destinations") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        url = str(row.get("url") or "").strip()
        auth_env = str(row.get("auth_env") or "").strip()
        if not name or not url:
            continue
        destinations.append({"name": name, "url": url, "auth_env": auth_env})
    default = " ".join(str(settings.get("defaultAgent") or "").split())
    if default and not any(row["name"].casefold() == default.casefold() for row in destinations):
        default = ""
    return {"default": default, "destinations": destinations}


def stored_settings(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT enabled, settings_json FROM plugin_settings WHERE plugin_id = ?",
        (PLUGIN_ID,),
    ).fetchone()
    if row is None:
        return {"enabled": False, "settings": {"defaultAgent": "", "destinations": []}}
    raw = json.loads(row["settings_json"] or "{}")
    if not isinstance(raw, dict):
        raw = {}
    destinations = raw.get("destinations")
    if not isinstance(destinations, list):
        destinations = []
    return {
        "enabled": bool(row["enabled"]),
        "settings": {
            "defaultAgent": str(raw.get("defaultAgent") or ""),
            "destinations": destinations,
        },
    }


def write_settings(conn: sqlite3.Connection, *, enabled: bool, settings: dict, stamp: str) -> dict:
    cleaned = {
        "defaultAgent": str(settings.get("defaultAgent") or ""),
        "destinations": clean_destinations(settings.get("destinations") or []),
    }
    view = destination_view(cleaned)
    cleaned["defaultAgent"] = view["default"]
    cleaned["destinations"] = view["destinations"]
    conn.execute(
        """
        INSERT INTO plugin_settings (plugin_id, enabled, settings_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (plugin_id) DO UPDATE SET
            enabled = excluded.enabled,
            settings_json = excluded.settings_json,
            updated_at = excluded.updated_at
        """,
        (PLUGIN_ID, 1 if enabled else 0, json.dumps(cleaned, ensure_ascii=False), stamp),
    )
    conn.commit()
    return view


def clean_destinations(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("destinations must be a list")
    rows = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each destination needs a name and URL.")
        name = clean_destination_name(item.get("name"))
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"{name} is already a cloud agent.")
        seen.add(folded)
        url, _ = webhook_parts(name, {"url": str(item.get("url") or ""), "auth_env": item.get("auth_env")})
        auth_env = clean_auth_env(item.get("auth_env"))
        row = {"name": name, "url": url, "auth_env": auth_env or ""}
        rows.append(row)
    return rows


def clean_destination_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise ValueError("Name the cloud agent in 80 characters or fewer.")
    if name.casefold() == "default":
        raise ValueError("Choose another name for the cloud agent.")
    return name


def clean_auth_env(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not AUTH_ENV_NAME.fullmatch(text):
        raise ValueError("Auth env must be an environment variable name, not the secret.")
    return text


def webhook_parts(name, raw):
    """Validate one destination. auth_env is a variable name; the secret stays in the environment."""
    auth_env = None
    if isinstance(raw, str):
        url = raw.strip()
    elif isinstance(raw, dict) and isinstance(raw.get("url"), str):
        url = raw["url"].strip()
        auth = raw.get("auth_env")
        if auth is not None and str(auth).strip():
            auth_env = clean_auth_env(auth)
    else:
        url = ""
    parsed = urlparse(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"Webhook for {name} is not an HTTP(S) URL without credentials.")
    if len(url) > 300 or any(ch.isspace() for ch in url):
        raise ValueError(f"Webhook for {name} is not an HTTP(S) URL without credentials.")
    return url, auth_env


def match_destination(destinations: list[dict], query: str) -> dict:
    wanted = " ".join(str(query or "").split())
    if not wanted:
        raise ValueError("Name the cloud agent.")
    for row in destinations:
        if row["name"].casefold() == wanted.casefold():
            return row
    raise ValueError(f"Unknown agent {wanted}.")


def save_destination(conn: sqlite3.Connection, args: dict, *, stamp: str) -> dict:
    if not isinstance(args, dict):
        raise ValueError("JSON object required.")
    unknown = set(args) - {"op", "name", "new_name", "url", "auth_env"}
    if unknown:
        raise ValueError("Unknown webhook field.")
    op = args.get("op")
    current = stored_settings(conn)
    settings = dict(current["settings"])
    destinations = [dict(row) for row in destination_view(settings)["destinations"]]
    default = destination_view(settings)["default"]

    if op == "add":
        name = clean_destination_name(args.get("name"))
        if any(row["name"].casefold() == name.casefold() for row in destinations):
            raise ValueError(f"{name} is already a cloud agent.")
        url, _ = webhook_parts(name, {"url": str(args.get("url") or "")})
        auth_env = clean_auth_env(args.get("auth_env"))
        destinations.append({"name": name, "url": url, "auth_env": auth_env or ""})
    elif op == "edit":
        row = match_destination(destinations, args.get("name"))
        new_name = clean_destination_name(
            args.get("new_name") if args.get("new_name") is not None else row["name"]
        )
        if new_name.casefold() != row["name"].casefold() and any(
            other["name"].casefold() == new_name.casefold() for other in destinations
        ):
            raise ValueError(f"{new_name} is already a cloud agent.")
        url, _ = webhook_parts(new_name, {"url": str(args.get("url") or "")})
        auth_env = clean_auth_env(args.get("auth_env"))
        destinations = [item for item in destinations if item["name"].casefold() != row["name"].casefold()]
        destinations.append({"name": new_name, "url": url, "auth_env": auth_env or ""})
        if default and default.casefold() == row["name"].casefold():
            default = new_name
    elif op == "remove":
        row = match_destination(destinations, args.get("name"))
        destinations = [item for item in destinations if item["name"].casefold() != row["name"].casefold()]
        if default and default.casefold() == row["name"].casefold():
            default = ""
    elif op == "default":
        wanted = " ".join(str(args.get("name") or "").split())
        default = "" if not wanted else match_destination(destinations, wanted)["name"]
    else:
        raise ValueError("Unknown cloud-agent action.")

    if not destinations:
        default = ""
    return write_settings(
        conn,
        enabled=current["enabled"],
        settings={"defaultAgent": default, "destinations": destinations},
        stamp=stamp,
    )


def resolve_agent(conn: sqlite3.Connection, agent) -> tuple[str, str, str | None]:
    view = destination_view(stored_settings(conn)["settings"])
    destinations = view["destinations"]
    if not destinations:
        raise ValueError(
            "No agent webhooks configured. Add a cloud agent in Settings → Plugins."
        )
    query = " ".join(str(agent or "").split())
    if not query:
        query = view["default"]
    if not query:
        raise ValueError(
            "Name the agent to receive the list, or choose a default cloud agent in Settings."
        )
    try:
        row = match_destination(destinations, query)
    except ValueError:
        known = ", ".join(item["name"] for item in destinations)
        raise ValueError(f"Unknown agent {query}. Configured agents: {known}.") from None
    auth_env = row["auth_env"] or None
    return row["name"], row["url"], auth_env


def list_label(value) -> tuple[str, str]:
    name = " ".join(str(value or "").split())
    folded = name.casefold()
    if folded.endswith(" list"):
        folded = folded[:-5].rstrip()
    return name, folded


def note_items(text) -> list[str]:
    items = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^(?:[-*•]+|\d+[.)])\s+", "", line).strip()
        if line:
            items.append(line)
    if len(items) == 1 and "," in items[0]:
        parts = [" ".join(part.split()) for part in items[0].split(",") if part.strip()]
        if len(parts) > 1:
            return parts
    return items


def named_list(conn: sqlite3.Connection, list_name) -> tuple[str, list[str]]:
    _, wanted = list_label(list_name)
    if not wanted:
        raise ValueError("Name the list to send.")
    matches = []
    # Walk notes newest-first via the shared list helper pages.
    cursor = None
    while True:
        page = notes_mod.list_notes(conn, cursor=cursor, limit=100)
        for note in page["notes"]:
            _, label = list_label(note.get("type"))
            if label == wanted:
                matches.append(note)
        cursor = page.get("nextCursor")
        if not cursor:
            break
    if not matches:
        shown = " ".join(str(list_name or "").split())
        raise ValueError(f"No note named {shown}.")
    items = []
    for note in matches:
        items.extend(note_items(note.get("text")))
    if not items:
        raise ValueError(f'The note named {matches[0].get("type")} has no items.')
    return matches[0].get("type") or wanted, items


def post_agent_list(url: str, payload: dict, auth_env: str | None = None) -> dict:
    if list_poster is not None:
        return list_poster(url, payload, auth_env)
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    if auth_env:
        token = os.environ.get(auth_env) or ""
        if not token.strip():
            raise ValueError(f"{auth_env} is not set.")
        headers["Authorization"] = "Bearer " + token
    request = Request(url, body, headers, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            response.read(1024)
            code = response.status
    except HTTPError as exc:
        raise ValueError(f"The agent refused the list (HTTP {exc.code}).") from None
    except (OSError, URLError, TimeoutError, socket.timeout):
        raise ValueError("The agent webhook could not be reached.") from None
    if code not in (200, 201, 202, 204):
        raise ValueError(f"The agent refused the list (HTTP {code}).")
    return payload


def send_list(conn: sqlite3.Connection, args: dict) -> dict:
    """POST a named note list to one destination. Omit agent to use the Settings default."""
    if not isinstance(args, dict):
        raise ValueError("JSON object required.")
    list_name, items = named_list(conn, args.get("list_name"))
    agent, url, auth_env = resolve_agent(conn, args.get("agent"))
    payload = post_agent_list(
        url,
        {"from": "babette", "list": list_name, "items": items},
        auth_env,
    )
    return {
        "status": "sent",
        "agent": agent,
        "list": payload["list"],
        "items": payload["items"],
    }
