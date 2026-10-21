"""Kitchen HTTP API: session, shared reads/writes, LAN bind with origin allowlist.

ThreadingHTTPServer, stdlib only. Shared kitchen data lives in SQLite. Each
device has a cookie session (chat, turn, pane, surface, draft). Writes need
same-origin JSON and an Origin on the allowlist when Origin is sent. There is
no host gate. Default bind is 0.0.0.0.

Pass --web (or FESTIN_WEB) to also serve a built front end. Without it, static
files stay with Vite.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from festin import chats as chats_mod
from festin import household as household_mod
from festin import inbox as inbox_mod
from festin import log as log_mod
from festin import notes as notes_mod
from festin import plans as plans_mod
from festin import recipes as recipes_mod
from festin import settings as core_settings
from festin import weather as weather_mod
from festin.chat.engine import chat as run_chat
from festin.chat.flights import stop_request
from festin.chat.keys import model_key_is_set, model_key_source, resolve_model_key, write_model_key
from festin.chat.model_probe import probe_model
from festin.errors import NotFound, StaleState
from festin.plugins import host as plugins_host
from festin.plugins.printer import weekly as weekly_pick
from festin.schema import apply, connect

DEFAULT_INBOX_PORT = 8889

COOKIE = "festin_session"
SURFACES = frozenset({"tucked", "peek", "full"})
FIELDS = ("chat_id", "turn", "pane", "surface", "draft")
TURN_TTL = timedelta(minutes=10)
CHAT_HELD = "Babette is answering this chat on another device."
BODY_LIMIT = 57_000_000
BUSY = "Babette is still answering."
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
# Vite content hashes are at least eight url-safe characters before the extension.
_HASHED_ASSET = re.compile(r"-[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9]+)+$")
# Kitchen routes stay on the API even when --web is set. The inbox is a separate
# listener (InboxServer); it is not this handler.
_WEB_RESERVED = ("/api", "/photos", "/files", "/cards")
WEB_CACHE_LONG = "public, max-age=31536000, immutable"
WEB_CACHE_SHORT = "no-cache"
_WEB_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".webmanifest": "application/manifest+json",
    ".ico": "image/x-icon",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".map": "application/json",
    ".otf": "font/otf",
    ".ttf": "font/ttf",
    ".gif": "image/gif",
}
TERMINAL = frozenset({"done", "stopped", "error"})
_GUARDS: dict[str, threading.Lock] = {}
_GUARDS_LOCK = threading.Lock()


class MidTurn(Exception):
    """This session already holds a different turn."""


class ChatHeld(Exception):
    """Another session's live turn already holds this chat."""


class KitchenServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        db_path,
        *,
        origins=None,
        photos_dir=None,
        inbox_port=None,
        inbox_url=None,
        web_dir=None,
    ):
        self.db_path = str(db_path)
        self.origins = tuple(origin.rstrip("/") for origin in (origins or ()) if origin)
        # Kitchen files live beside the database: photos/ (chat and recipe photos),
        # files/ (chat text attachments), and cards/ (scans of the original recipe cards).
        self.data_dir = Path(db_path).resolve().parent
        self.photos_dir = Path(photos_dir) if photos_dir else self.data_dir / "photos"
        self.files_dir = self.data_dir / "files"
        self.cards_dir = self.data_dir / "cards"
        self.now = lambda: datetime.now(timezone.utc)
        # Extra arguments for the chat engine (tests pass a fake model here).
        self.chat_options = {}
        self.inbox_port = inbox_port
        # Where agents reach the inbox when the host exposes it (a tunnel, Funnel, a
        # router); Settings and the agent instructions show this instead of the local port.
        self.inbox_url = (inbox_url or "").rstrip("/") or None
        self.web_dir = Path(web_dir).expanduser().resolve() if web_dir else None
        self._inbox_httpd = None
        self._inbox_thread = None
        self._inbox_lock = threading.Lock()
        conn = connect(db_path)
        try:
            apply(conn)
            inbox_mod.ensure_inbox_key(conn)
            inbox_on = core_settings.get_settings(conn)["inbox_enabled"]
        finally:
            conn.close()
        super().__init__(server_address, Handler)
        if self.inbox_port is not None and inbox_on:
            self.start_inbox()

    def inbox_address(self) -> str:
        if self.inbox_url:
            return self.inbox_url
        host = self.server_address[0]
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        port = self.inbox_bound_port()
        if port is None:
            port = self.inbox_port if self.inbox_port not in (None, 0) else DEFAULT_INBOX_PORT
        return f"http://{host}:{port}"

    def inbox_bound_port(self) -> int | None:
        with self._inbox_lock:
            if self._inbox_httpd is None:
                return None
            return self._inbox_httpd.server_address[1]

    def start_inbox(self) -> None:
        with self._inbox_lock:
            if self.inbox_port is None or self._inbox_httpd is not None:
                return
            host = self.server_address[0]
            httpd = inbox_mod.InboxServer(
                (host, self.inbox_port),
                self.db_path,
                public_address=self._inbox_public_address(host, self.inbox_port),
            )
            # Port 0 picks an ephemeral port; refresh the public address.
            bound = httpd.server_address[1]
            httpd.public_address = self.inbox_url or self._inbox_public_address(host, bound).rstrip("/")
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            self._inbox_httpd = httpd
            self._inbox_thread = thread

    def stop_inbox(self) -> None:
        with self._inbox_lock:
            httpd = self._inbox_httpd
            self._inbox_httpd = None
            self._inbox_thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    def set_inbox_enabled(self, enabled: bool) -> None:
        if enabled:
            self.start_inbox()
        else:
            self.stop_inbox()

    def server_close(self):
        self.stop_inbox()
        super().server_close()

    def _inbox_public_address(self, host: str, port: int) -> str:
        shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
        return f"http://{shown}:{port}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_HEAD(self):
        return self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path.startswith("/photos/"):
                return self._send_file(self.server.photos_dir, path[len("/photos/"):])
            if path.startswith("/files/"):
                return self._send_file(self.server.files_dir, path[len("/files/"):])
            if path.startswith("/cards/"):
                return self._send_file(self.server.cards_dir, path[len("/cards/"):])
            if path.startswith("/slips/"):
                return self._send_file(self.server.data_dir / "slips", path[len("/slips/"):])
            if path.startswith("/api/speak/"):
                return self._speak_get(path)
            if path == "/api/plugins" or path.startswith("/api/plugins/"):
                return self._plugins_get(path)
            if path == "/api/session":
                return self._session(None)
            if path == "/api/settings":
                return self._get_settings()
            if path == "/api/weather":
                return self._get_weather()
            if path == "/api/recipes":
                with self._db() as conn:
                    return self._send(
                        200,
                        recipes_mod.list_recipes(
                            conn,
                            q=_q(query, "q"),
                            cursor=_q(query, "cursor") or None,
                            limit=_limit(query),
                            sample=_q(query, "sample") in ("1", "true"),
                            categories=[c for c in _q(query, "category").split(",") if c] or None,
                            queued=_q(query, "queued") in ("1", "true"),
                        ),
                    )
            if path.startswith("/api/recipes/"):
                with self._db() as conn:
                    return self._send(200, recipes_mod.get_recipe(conn, _id_after(path, "/api/recipes/")))
            if path == "/api/notes":
                with self._db() as conn:
                    return self._send(
                        200,
                        notes_mod.list_notes(
                            conn,
                            q=_q(query, "q"),
                            cursor=_q(query, "cursor") or None,
                            limit=_limit(query),
                        ),
                    )
            if path.startswith("/api/notes/"):
                with self._db() as conn:
                    return self._send(200, notes_mod.get_note(conn, _id_after(path, "/api/notes/")))
            if path.startswith("/api/household-context/"):
                with self._db() as conn:
                    return self._send(
                        200,
                        household_mod.get_section(
                            conn, _id_after(path, "/api/household-context/")
                        ),
                    )
            if path == "/api/chats":
                with self._db() as conn:
                    return self._send(
                        200,
                        chats_mod.list_chats(
                            conn,
                            q=_q(query, "q"),
                            cursor=_q(query, "cursor") or None,
                            limit=_limit(query),
                        ),
                    )
            if path.startswith("/api/chats/"):
                with self._db() as conn:
                    return self._send(200, chats_mod.get_chat(conn, _id_after(path, "/api/chats/")))
            if path.startswith("/api/plans/"):
                week = _id_after(path, "/api/plans/")
                with self._db() as conn:
                    plan = plans_mod.get_plan(conn, week)
                self._maybe_weekly_pick(for_week=week)
                return self._send(200, plan)
            if path == "/api/log":
                with self._db() as conn:
                    return self._send(
                        200,
                        log_mod.list_log(
                            conn,
                            before=_q(query, "before") or None,
                            limit=_limit(query),
                        ),
                    )
            if self._serve_web(path):
                return
            return self._send(404, {"error": "Not found"})
        except (NotFound, KeyError) as exc:
            return self._send(404, {"error": str(exc) or "Not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._write_allowed():
            return self._send(403, {"error": "Same-origin JSON required"})
        try:
            body = self._read_body()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc) or "Bad request"})
        if path == "/api/chat":
            return self._chat(body)
        if path == "/api/stop":
            return self._send(200, stop_request(request_id=body.get("request_id"), submission_id=body.get("submission_id")))
        try:
            if path == "/api/speak":
                return self._speak_post(body)
            if path == "/api/settings/model-key":
                return self._send(200, self._save_model_key(body))
            if path == "/api/settings/model-test":
                return self._send(200, self._test_model())
            if path == "/api/settings/inbox-key":
                return self._send(200, self._rotate_inbox_key())
            with self._db() as conn:
                if path == "/api/plugins" or path.startswith("/api/plugins/"):
                    return self._plugins_post(conn, path, body)
                if path == "/api/settings":
                    return self._send(200, self._save_settings(conn, body))
                if path == "/api/recipes":
                    return self._send(201, recipes_mod.create_recipe(conn, body, now=self.server.now()))
                if path.endswith("/photos") and path.startswith("/api/recipes/"):
                    recipe_id = _id_after(path[: -len("/photos")], "/api/recipes/")
                    return self._send(
                        200,
                        recipes_mod.update_photos(
                            conn, recipe_id, body, self.server.photos_dir, now=self.server.now()
                        ),
                    )
                if path.endswith("/cooked") and path.startswith("/api/recipes/"):
                    recipe_id = _id_after(path[: -len("/cooked")], "/api/recipes/")
                    return self._send(
                        200, recipes_mod.mark_cooked(conn, recipe_id, body, now=self.server.now())
                    )
                if path.endswith("/clear-cooks") and path.startswith("/api/recipes/"):
                    recipe_id = _id_after(path[: -len("/clear-cooks")], "/api/recipes/")
                    return self._send(
                        200, recipes_mod.clear_cooks(conn, recipe_id, body, now=self.server.now())
                    )
                if path.startswith("/api/recipes/"):
                    return self._send(
                        200,
                        recipes_mod.edit_recipe(
                            conn, _id_after(path, "/api/recipes/"), body, now=self.server.now()
                        ),
                    )
                if path == "/api/notes":
                    return self._send(201, notes_mod.create_note(conn, body, now=self.server.now()))
                if path.endswith("/toggle") and path.startswith("/api/notes/"):
                    note_id = _id_after(path[: -len("/toggle")], "/api/notes/")
                    return self._send(
                        200, notes_mod.toggle_note(conn, note_id, body, now=self.server.now())
                    )
                if path.startswith("/api/notes/"):
                    return self._send(
                        200,
                        notes_mod.edit_note(
                            conn, _id_after(path, "/api/notes/"), body, now=self.server.now()
                        ),
                    )
                if path == "/api/chats":
                    token = _cookie(self.headers.get("Cookie"))
                    session = _row_for_cookie(conn, token, self.server.now())
                    chat = chats_mod.create_chat(conn, session["id"], body, now=self.server.now())
                    return self._send(201, chat, session["id"])
                if path.startswith("/api/chats/"):
                    return self._send(
                        200,
                        chats_mod.rename_chat(
                            conn, _id_after(path, "/api/chats/"), body, now=self.server.now()
                        ),
                    )
                if path.startswith("/api/plans/"):
                    return self._send(
                        200,
                        plans_mod.save_plan(
                            conn, _id_after(path, "/api/plans/"), body, now=self.server.now()
                        ),
                    )
                if path == "/api/plan":
                    week = body.get("weekStart")
                    if not isinstance(week, str) or not week.strip():
                        raise ValueError("weekStart is required")
                    return self._send(
                        200, plans_mod.save_plan(conn, week.strip(), body, now=self.server.now())
                    )
            return self._send(404, {"error": "Not found"})
        except StaleState as exc:
            return self._send(409, {"error": str(exc)})
        except (NotFound, KeyError) as exc:
            return self._send(404, {"error": str(exc) or "Not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})

    def do_PUT(self):
        path = urlparse(self.path).path
        if path == "/api/session":
            if not self._write_allowed():
                return self._send(403, {"error": "Same-origin JSON required"})
            try:
                changes = _parse_changes(self._read_body())
            except (ValueError, json.JSONDecodeError) as exc:
                return self._send(400, {"error": str(exc) or "Bad session"})
            return self._session(changes)
        if not self._write_allowed():
            return self._send(403, {"error": "Same-origin JSON required"})
        try:
            body = self._read_body()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc) or "Bad request"})
        try:
            with self._db() as conn:
                if path.startswith("/api/plugins/"):
                    plugin_id, action = plugins_host.parse_plugin_path(path)
                    if action:
                        raise NotFound("Not found")
                    return self._send(
                        200,
                        plugins_host.update_plugin(conn, plugin_id, body, now=self.server.now()),
                    )
                if path.startswith("/api/household-context/"):
                    return self._send(
                        200,
                        household_mod.put_section(
                            conn,
                            _id_after(path, "/api/household-context/"),
                            body,
                            now=self.server.now(),
                        ),
                    )
                if path.startswith("/api/recipes/"):
                    return self._send(
                        200,
                        recipes_mod.edit_recipe(
                            conn, _id_after(path, "/api/recipes/"), body, now=self.server.now()
                        ),
                    )
                if path.startswith("/api/notes/"):
                    return self._send(
                        200,
                        notes_mod.edit_note(
                            conn, _id_after(path, "/api/notes/"), body, now=self.server.now()
                        ),
                    )
                if path.startswith("/api/chats/"):
                    return self._send(
                        200,
                        chats_mod.rename_chat(
                            conn, _id_after(path, "/api/chats/"), body, now=self.server.now()
                        ),
                    )
                if path.startswith("/api/plans/"):
                    return self._send(
                        200,
                        plans_mod.save_plan(
                            conn, _id_after(path, "/api/plans/"), body, now=self.server.now()
                        ),
                    )
            return self._send(404, {"error": "Not found"})
        except StaleState as exc:
            return self._send(409, {"error": str(exc)})
        except (NotFound, KeyError) as exc:
            return self._send(404, {"error": str(exc) or "Not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not self._write_allowed():
            return self._send(403, {"error": "Same-origin JSON required"})
        try:
            length = int(self.headers.get("Content-Length") or "0")
            body = self._read_body() if length else {}
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc) or "Bad request"})
        try:
            with self._db() as conn:
                if path.startswith("/api/recipes/"):
                    return self._send(
                        200, recipes_mod.delete_recipe(conn, _id_after(path, "/api/recipes/"), body)
                    )
                if path.startswith("/api/notes/"):
                    return self._send(
                        200, notes_mod.delete_note(conn, _id_after(path, "/api/notes/"), body)
                    )
                if path.startswith("/api/chats/"):
                    return self._send(
                        200, chats_mod.delete_chat(conn, _id_after(path, "/api/chats/"), body)
                    )
            return self._send(404, {"error": "Not found"})
        except StaleState as exc:
            return self._send(409, {"error": str(exc)})
        except (NotFound, KeyError) as exc:
            return self._send(404, {"error": str(exc) or "Not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})

    def _speak_post(self, body: dict):
        from festin.plugins.voice import speak as voice_speak

        with self._db() as conn:
            if not plugins_host.enabled(conn, "voice"):
                raise NotFound("That plugin is off.")
            stored = plugins_host._stored(conn, plugins_host._require("voice"))
            result = voice_speak.speak(
                body.get("text", ""),
                data_dir=self.server.data_dir,
                settings=stored["settings"],
            )
        status = 202 if result.get("status") == "rendering" else 200
        return self._send(status, result)

    def _speak_get(self, path: str):
        from festin.plugins.voice import speak as voice_speak

        with self._db() as conn:
            if not plugins_host.enabled(conn, "voice"):
                return self._send(404, {"error": "That plugin is off."})
        key = path[len("/api/speak/") :]
        if "/" in key or not key:
            return self._send(404, {"error": "Reading not found."})
        query = parse_qs(urlparse(self.path).query)
        status, value = voice_speak.speech_result(key, data_dir=self.server.data_dir)
        if status == "rendering":
            return self._send(202, {"status": "rendering"})
        if status == "error":
            return self._send(400, {"error": value or "The voice could not be rendered."})
        if status == "missing":
            return self._send(404, {"error": "Reading not found."})
        if _q(query, "status") == "1":
            return self._send(200, {"status": "ready", "url": "/api/speak/" + key})
        data = value if isinstance(value, (bytes, bytearray)) else b""
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write_body(data)

    def _plugins_get(self, path: str):
        with self._db() as conn:
            if path == "/api/plugins":
                return self._send(200, {"plugins": plugins_host.list_plugins(conn)})
            plugin_id, action = plugins_host.parse_plugin_path(path)
            if not action:
                return self._send(200, plugins_host.get_plugin(conn, plugin_id))
            if action == "feed":
                return self._send(200, plugins_host.feed(plugin_id))
            return self._send(404, {"error": "Not found"})

    def _plugins_post(self, conn, path: str, body: dict):
        plugin_id, action = plugins_host.parse_plugin_path(path)
        if not action or action == "feed":
            raise NotFound("Not found")
        return self._send(
            200,
            plugins_host.call_action(
                conn,
                plugin_id,
                action,
                body,
                data_dir=self.server.data_dir,
                now=self.server.now(),
            ),
        )

    def _get_settings(self):
        with self._db() as conn:
            return self._send(200, self._settings_body(conn))

    def _get_weather(self):
        with self._db() as conn:
            settings = core_settings.get_settings(conn)
            return self._send(200, weather_mod.weather_forecast(settings))

    def _save_settings(self, conn, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        current = core_settings.get_settings(conn)
        expected = body.get("expected_updated_at", body.get("expectedUpdatedAt"))
        if expected is not None and expected != current["updated_at"]:
            raise StaleState("Settings changed. Refresh before saving.")
        inbox_enabled = _inbox_enabled(body)
        core_settings.update_settings(
            conn,
            table_name=_pick(body, "tableName", "table_name"),
            week_start_day=_pick(body, "weekStart", "week_start_day"),
            dinner_hour=_pick(body, "dinnerHour", "dinner_hour"),
            weather_location=_weather_location(body),
            model_base_url=_pick(body, "modelBaseUrl", "model_base_url"),
            model_name=_pick(body, "modelName", "model_name"),
            inbox_enabled=inbox_enabled,
            chat_wet_band=_pick(body, "chatWetBand", "chat_wet_band"),
            now=self.server.now(),
        )
        if inbox_enabled is not None:
            self.server.set_inbox_enabled(inbox_enabled)
        return self._settings_body(conn)

    def _settings_body(self, conn) -> dict:
        raw = core_settings.get_settings(conn)
        return _public_settings(
            raw,
            model_key_is_set(self.server.data_dir),
            model_key_source(self.server.data_dir, raw["model_base_url"]),
            inbox_address=self.server.inbox_address() if self.server.inbox_port is not None else "",
        )

    def _save_model_key(self, body: dict) -> dict:
        if "key" not in body:
            raise ValueError("API key must be a string.")
        write_model_key(self.server.data_dir, body.get("key"))
        with self._db() as conn:
            return self._settings_body(conn)

    def _rotate_inbox_key(self) -> dict:
        with self._db() as conn:
            key = inbox_mod.rotate_inbox_key(conn)
            settings = self._settings_body(conn)
        address = settings["inbox"]["address"]
        return {
            **settings,
            "inboxKey": {
                "key": key,
                "address": address,
                "exampleCurl": inbox_mod.example_curl(address, key),
            },
        }

    def _test_model(self) -> dict:
        with self._db() as conn:
            raw = core_settings.get_settings(conn)
        key = resolve_model_key(self.server.data_dir, raw["model_base_url"])
        return probe_model(raw["model_base_url"], raw["model_name"], key)

    def _maybe_weekly_pick(self, *, for_week: str | None = None) -> None:
        """Kick Babette's weekly slip pick without blocking the request."""
        options = self.server.chat_options or {}
        weekly_pick.trigger_weekly_pick(
            db_path=self.server.db_path,
            data_dir=self.server.data_dir,
            completer=options.get("weekly_pick_completer"),
            for_week=for_week,
        )

    def _session(self, changes):
        token = _cookie(self.headers.get("Cookie"))
        conn = connect(self.server.db_path)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            row = _row_for_cookie(conn, token, self.server.now())
            now = self.server.now()
            if changes is None:
                conn.execute("BEGIN IMMEDIATE")
                _expire_stale(conn, now)
                conn.commit()
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (row["id"],)).fetchone()
                self._send(200, _public_session(row), row["id"])
                self._maybe_weekly_pick()
                return
            guard = _guard(row["id"])
            with guard:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    _expire_stale(conn, now)
                    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (row["id"],)).fetchone()
                    values = _apply_changes(conn, row, changes, now)
                except MidTurn:
                    conn.rollback()
                    self._send(409, {"error": "This session is mid-turn."}, row["id"])
                    return
                except ChatHeld:
                    conn.rollback()
                    self._send(409, {"error": CHAT_HELD}, row["id"])
                    return
                except ValueError as exc:
                    conn.rollback()
                    self._send(400, {"error": str(exc)}, row["id"])
                    return
                conn.execute(
                    """
                    UPDATE sessions
                    SET chat_id = ?, turn_json = ?, pane = ?, surface = ?, draft = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        values["chat_id"],
                        values["turn_json"],
                        values["pane"],
                        values["surface"],
                        values["draft"],
                        now.isoformat(),
                        row["id"],
                    ),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (row["id"],)).fetchone()
            self._send(200, _public_session(row), row["id"])
        finally:
            conn.close()

    def _chat(self, body: dict) -> None:
        """One chat turn as NDJSON, as live streams it. The turn locks this device's chat."""
        token = _cookie(self.headers.get("Cookie"))
        conn = connect(self.server.db_path)
        conn.execute("PRAGMA busy_timeout = 5000")
        held = None  # the session whose turn this request took, if any
        try:
            row = _row_for_cookie(conn, token, self.server.now())
            session_id = row["id"]
            turn_id = body.get("submission_id") if isinstance(body.get("submission_id"), str) else str(uuid.uuid4())
            # Take the turn: a device with no chat yet gets a fresh one.
            with _guard(session_id):
                conn.execute("BEGIN IMMEDIATE")
                try:
                    now = self.server.now()
                    _expire_stale(conn, now)
                    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
                    changes = {"turn": {"id": turn_id}}
                    if not row["chat_id"]:
                        changes["chat_id"] = str(uuid.uuid4())
                    values = _apply_changes(conn, row, changes, now)
                except (MidTurn, ChatHeld) as exc:
                    conn.rollback()
                    return self._send(409, {"error": CHAT_HELD if isinstance(exc, ChatHeld) else BUSY}, session_id)
                except ValueError as exc:
                    conn.rollback()
                    return self._send(400, {"error": str(exc)}, session_id)
                conn.execute(
                    "UPDATE sessions SET chat_id = ?, turn_json = ?, updated_at = ? WHERE id = ?",
                    (values["chat_id"], values["turn_json"], now.isoformat(), session_id),
                )
                conn.commit()
                held = session_id
            chat_id = values["chat_id"]

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("Set-Cookie", f"{COOKIE}={session_id}; HttpOnly; Path=/; SameSite=Lax")
            self.end_headers()
            self.close_connection = True
            alive = True
            ended = False

            # A browser that goes away does not stop the turn or leave the chat locked.
            def emit(event):
                nonlocal alive, ended
                ended = ended or event.get("type") in TERMINAL
                if not alive:
                    return
                try:
                    self.wfile.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
                    self.wfile.flush()
                except OSError:
                    alive = False

            try:
                text = str(body.get("text") or "").strip()
                if not text:
                    raise ValueError("Write a message.")
                week = body.get("week") or core_settings.week_bounds(conn)[0].isoformat()
                outcome = run_chat(
                    conn,
                    text=text,
                    week=week,
                    chat_id=body.get("chat_id"),
                    session_chat_id=chat_id,
                    data_dir=self.server.data_dir,
                    photos=body.get("photos") or [],
                    files=body.get("files") or [],
                    retry=bool(body.get("retry")),
                    editor_plan=body.get("plan"),
                    expected_messages=body.get("expected_messages"),
                    submission_id=body.get("submission_id"),
                    emit=emit,
                    context=body.get("context"),
                    **self.server.chat_options,
                )
                # A deduplicated submission returns without a stream; close it as done.
                if not ended:
                    emit({"type": "stopped"} if isinstance(outcome, dict) and outcome.get("stopped") else {"type": "done", "ok": True})
            except StaleState as exc:
                if not ended:
                    emit({"type": "error", "error": str(exc), "status": 409})
            except (ValueError, KeyError) as exc:
                if not ended:
                    emit({"type": "error", "error": str(exc), "status": 400})
            except Exception as exc:  # noqa: BLE001 - the stream must always end
                if not ended:
                    emit({"type": "error", "error": "Request failed (" + type(exc).__name__ + "). Check the connection and model, then retry.", "status": 400})
        finally:
            if held:
                try:
                    conn.execute("UPDATE sessions SET turn_json = NULL, updated_at = ? WHERE id = ?", (self.server.now().isoformat(), held))
                    conn.commit()
                except Exception:  # noqa: BLE001 - the stale-turn expiry frees it otherwise
                    pass
            conn.close()

    def _send_file(self, folder: Path, name: str) -> None:
        name = unquote(name)
        file = folder / name
        if not FILE_NAME.match(name) or not file.is_file():
            return self._send(404, {"error": "Not found"})
        data = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        self._write_body(data)

    def _serve_web(self, path: str) -> bool:
        """Serve the built front end. True when this request was answered."""
        web_dir = self.server.web_dir
        if web_dir is None or _web_skipped(path):
            return False
        rel = _web_relative(path)
        if rel is None:
            self._send(403, {"error": "Not found"})
            return True
        root = web_dir.resolve()
        if rel in ("", "index.html"):
            self._send_web_file(root / "index.html", root, long_cache=False)
            return True
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self._send(403, {"error": "Not found"})
            return True
        if candidate.is_file():
            self._send_web_file(candidate, root, long_cache=_web_long_cache(rel))
            return True
        # A missing hashed bundle must not become the shell (the client would
        # treat HTML as a script). Anything else is an app route.
        if rel == "assets" or rel.startswith("assets/"):
            self._send(404, {"error": "Not found"})
            return True
        self._send_web_file(root / "index.html", root, long_cache=False)
        return True

    def _send_web_file(self, file: Path, root: Path, *, long_cache: bool) -> None:
        try:
            file = file.resolve()
            file.relative_to(root)
        except ValueError:
            self._send(403, {"error": "Not found"})
            return
        if not file.is_file():
            self._send(404, {"error": "Not found"})
            return
        try:
            data = file.read_bytes()
        except OSError:
            self._send(404, {"error": "Not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", _web_type(file))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", WEB_CACHE_LONG if long_cache else WEB_CACHE_SHORT)
        self.end_headers()
        self._write_body(data)

    def _write_body(self, data: bytes) -> None:
        if self.command != "HEAD":
            self.wfile.write(data)

    def _db(self):
        conn = connect(self.server.db_path)
        conn.execute("PRAGMA busy_timeout = 5000")
        return _closing(conn)

    def _write_allowed(self) -> bool:
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        origin = origin.rstrip("/")
        host = self.headers.get("Host", "")
        allowed = {item.rstrip("/") for item in self.server.origins}
        if host:
            allowed.add(f"http://{host}")
            allowed.add(f"https://{host}")
        return origin in allowed

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length < 0:
            raise ValueError("Request too large or empty")
        if length > BODY_LIMIT:
            raise ValueError(
                "Request too large. Keep the message under 57 MB "
                "(documents plus up to four photos)."
            )
        raw = self.rfile.read(length) if length else b""
        if not raw:
            raise ValueError("JSON object required")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON object required")
        return data

    def _send(self, status: int, payload: dict, token: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if token:
            self.send_header("Set-Cookie", f"{COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax")
        self.end_headers()
        self._write_body(body)


class _closing:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()
        return False

def _public_settings(
    raw: dict,
    key_set: bool,
    key_source: str = "none",
    *,
    inbox_address: str = "",
) -> dict:
    return {
        "tableName": raw["table_name"],
        "dinnerHour": raw["dinner_hour"],
        "weekStart": raw["week_start_day"],
        "weather": raw["weather"],
        "updatedAt": raw["updated_at"],
        "model": {
            "baseUrl": raw["model_base_url"],
            "name": raw["model_name"],
            "keySet": bool(key_set),
            "keySource": key_source if key_source in ("file", "env", "none") else "none",
        },
        "inbox": {
            "enabled": bool(raw.get("inbox_enabled", True)),
            "address": inbox_address,
            "keySet": bool(raw.get("inbox_key_hash")),
        },
        "chatWetBand": int(raw.get("chat_wet_band", 45)),
    }


def _pick(body: dict, camel: str, snake: str):
    if camel in body:
        return body[camel]
    if snake in body:
        return body[snake]
    return None


def _weather_location(body: dict):
    if "weatherLocation" in body:
        return body["weatherLocation"]
    if "weather_location" in body:
        return body["weather_location"]
    weather = body.get("weather")
    if isinstance(weather, dict) and "location" in weather:
        return weather["location"]
    return None


def _inbox_enabled(body: dict):
    if "inboxEnabled" in body:
        return body["inboxEnabled"]
    if "inbox_enabled" in body:
        return body["inbox_enabled"]
    inbox = body.get("inbox")
    if isinstance(inbox, dict) and "enabled" in inbox:
        return inbox["enabled"]
    return None


def _q(query: dict, name: str) -> str:
    values = query.get(name) or []
    return values[0] if values else ""


def _limit(query: dict) -> int:
    raw = _q(query, "limit")
    if not raw:
        return recipes_mod.PAGE_SIZE
    try:
        return int(raw)
    except ValueError:
        return recipes_mod.PAGE_SIZE


def _id_after(path: str, prefix: str) -> str:
    rest = path[len(prefix) :]
    if not rest or "/" in rest:
        raise NotFound("Not found")
    return unquote(rest)


def _row_for_cookie(conn, token, now):
    row = None
    if token:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (token,)).fetchone()
    if row is not None:
        return row
    stamp = now.isoformat()
    new_id = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (id, draft, created_at, updated_at) VALUES (?, '', ?, ?)",
        (new_id, stamp, stamp),
    )
    conn.commit()
    return conn.execute("SELECT * FROM sessions WHERE id = ?", (new_id,)).fetchone()


def _expire_stale(conn, now: datetime) -> None:
    rows = conn.execute("SELECT id, turn_json FROM sessions WHERE turn_json IS NOT NULL").fetchall()
    stale = []
    for row in rows:
        held = _held_at(row["turn_json"])
        if held is None or now - held >= TURN_TTL:
            stale.append(row["id"])
    stamp = now.isoformat()
    for session_id in stale:
        conn.execute(
            "UPDATE sessions SET turn_json = NULL, updated_at = ? WHERE id = ?",
            (stamp, session_id),
        )


def _held_at(turn_json: str):
    try:
        raw = json.loads(turn_json)["held_at"]
        held = datetime.fromisoformat(raw)
    except (KeyError, TypeError, ValueError):
        return None
    if held.tzinfo is None:
        held = held.replace(tzinfo=timezone.utc)
    return held


def _apply_changes(conn, row, changes: dict, now: datetime) -> dict:
    current = _public_turn(row["turn_json"])
    turn = current
    if "turn" in changes:
        turn = changes["turn"]
        if current and turn and current["id"] != turn["id"]:
            raise MidTurn()
    chat_id = row["chat_id"]
    if "chat_id" in changes:
        chat_id = changes["chat_id"]
        still_held = turn if "turn" in changes else current
        if current and still_held and chat_id != row["chat_id"]:
            raise MidTurn()
    if turn is not None:
        if not chat_id:
            raise ValueError("A turn needs a chat")
        holder = conn.execute(
            """
            SELECT id FROM sessions
            WHERE chat_id = ? AND id != ? AND turn_json IS NOT NULL
            """,
            (chat_id, row["id"]),
        ).fetchone()
        if holder is not None:
            raise ChatHeld()
    if turn is None:
        turn_json = None
    elif "turn" in changes:
        stored = dict(turn)
        stored["held_at"] = now.isoformat()
        turn_json = _dump(stored)
    else:
        turn_json = row["turn_json"]
    pane = changes["pane"] if "pane" in changes else row["pane"]
    surface = changes["surface"] if "surface" in changes else row["surface"]
    draft = changes["draft"] if "draft" in changes else row["draft"]
    return {
        "chat_id": chat_id,
        "turn_json": turn_json,
        "pane": pane,
        "surface": surface,
        "draft": draft,
    }


def _public_turn(turn_json):
    if not turn_json:
        return None
    turn = json.loads(turn_json)
    turn.pop("held_at", None)
    return turn


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_changes(data: dict) -> dict:
    unknown = set(data) - set(FIELDS)
    if unknown:
        raise ValueError("Unknown session field")
    changes = {}
    if "chat_id" in data:
        changes["chat_id"] = _short(data["chat_id"], "chat_id")
    if "pane" in data:
        changes["pane"] = _short(data["pane"], "pane")
    if "surface" in data:
        changes["surface"] = _surface(data["surface"])
    if "draft" in data:
        draft = data["draft"]
        if not isinstance(draft, str):
            raise ValueError("draft must be text")
        if len(draft) > 16000:
            raise ValueError("draft is too long")
        changes["draft"] = draft
    if "turn" in data:
        changes["turn"] = _turn(data["turn"])
    return changes


def _short(value, label: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    text = value.strip()
    if not text:
        return None
    if len(text) > 80:
        raise ValueError(f"{label} is too long")
    return text


def _web_skipped(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _WEB_RESERVED)


def _web_relative(path: str) -> str | None:
    """URL path as a relative posix path, or None when it tries to leave the root."""
    decoded = unquote(path)
    if "\x00" in decoded or "\\" in decoded or not decoded.startswith("/"):
        return None
    parts: list[str] = []
    for part in decoded.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    return "/".join(parts)


def _web_long_cache(rel: str) -> bool:
    if not rel.startswith("assets/"):
        return False
    return _HASHED_ASSET.search(rel.rsplit("/", 1)[-1]) is not None


def _web_type(path: Path) -> str:
    return _WEB_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _surface(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("surface must be tucked, peek, or full")
    surface = value.strip().casefold()
    if surface not in SURFACES:
        raise ValueError("surface must be tucked, peek, or full")
    return surface


def _turn(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("A turn must be an object")
    turn_id = value.get("id")
    if not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id.strip()) > 80:
        raise ValueError("A turn needs an id")
    cleaned = {"id": turn_id.strip()}
    phase = value.get("phase")
    if phase is not None:
        if not isinstance(phase, str) or not phase.strip() or len(phase.strip()) > 40:
            raise ValueError("turn phase must be short text")
        cleaned["phase"] = phase.strip()
    return cleaned


def _public_session(row) -> dict:
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "turn": _public_turn(row["turn_json"]),
        "pane": row["pane"],
        "surface": row["surface"],
        "draft": row["draft"],
    }


def _cookie(header):
    if not header:
        return None
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == COOKIE and value:
            return value
    return None


def _guard(session_id: str) -> threading.Lock:
    with _GUARDS_LOCK:
        lock = _GUARDS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _GUARDS[session_id] = lock
        return lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m festin.server")
    parser.add_argument("db_path")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--inbox-port",
        type=int,
        default=DEFAULT_INBOX_PORT,
        help=f"Incoming-recipes listener port (default {DEFAULT_INBOX_PORT}).",
    )
    parser.add_argument(
        "--inbox-url",
        default=os.environ.get("FESTIN_INBOX_URL", ""),
        help="Public address of the inbox, when the host exposes it (or FESTIN_INBOX_URL).",
    )
    parser.add_argument(
        "--origin",
        action="append",
        default=[],
        help="Allowed Origin for writes (repeatable). Same-host Origin is always allowed.",
    )
    parser.add_argument(
        "--web",
        default=os.environ.get("FESTIN_WEB") or None,
        help="Serve the built front end from this directory (or FESTIN_WEB).",
    )
    args = parser.parse_args(argv)
    web = args.web.strip() if isinstance(args.web, str) else None
    server = KitchenServer(
        (args.host, args.port),
        args.db_path,
        origins=args.origin,
        inbox_port=args.inbox_port,
        inbox_url=args.inbox_url,
        web_dir=web or None,
    )
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    if server.web_dir is not None:
        print(f"web from {server.web_dir}", flush=True)
    if server.inbox_bound_port() is not None:
        print(f"inbox on {server.inbox_address()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
