"""Kitchen HTTP API: session, shared reads/writes, LAN bind with origin allowlist.

ThreadingHTTPServer, stdlib only. Shared kitchen data lives in SQLite. Each
device has a cookie session (chat, turn, pane, surface, draft). Writes need
same-origin JSON and an Origin on the allowlist when Origin is sent. There is
no host gate. Default bind is 0.0.0.0.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from festin import chats as chats_mod
from festin import notes as notes_mod
from festin import plans as plans_mod
from festin import recipes as recipes_mod
from festin import settings as core_settings
from festin import weather as weather_mod
from festin.chat.engine import chat as run_chat
from festin.chat.flights import stop_request
from festin.errors import NotFound, StaleState
from festin.schema import apply, connect

COOKIE = "festin_session"
SURFACES = frozenset({"tucked", "peek", "full"})
FIELDS = ("chat_id", "turn", "pane", "surface", "draft")
TURN_TTL = timedelta(minutes=10)
CHAT_HELD = "Babette is answering this chat on another device."
BODY_LIMIT = 57_000_000
BUSY = "Babette is still answering."
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
TERMINAL = frozenset({"done", "stopped", "error"})
_GUARDS: dict[str, threading.Lock] = {}
_GUARDS_LOCK = threading.Lock()


class MidTurn(Exception):
    """This session already holds a different turn."""


class ChatHeld(Exception):
    """Another session's live turn already holds this chat."""


class KitchenServer(ThreadingHTTPServer):
    def __init__(self, server_address, db_path, *, origins=None, photos_dir=None):
        self.db_path = str(db_path)
        self.origins = tuple(origin.rstrip("/") for origin in (origins or ()) if origin)
        # Kitchen files live beside the database: photos/ (chat and recipe photos) and
        # cards/ (scans of the original recipe cards).
        self.data_dir = Path(db_path).resolve().parent
        self.photos_dir = Path(photos_dir) if photos_dir else self.data_dir / "photos"
        self.cards_dir = self.data_dir / "cards"
        self.now = lambda: datetime.now(timezone.utc)
        # Extra arguments for the chat engine (tests pass a fake model here).
        self.chat_options = {}
        conn = connect(db_path)
        try:
            apply(conn)
        finally:
            conn.close()
        super().__init__(server_address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path.startswith("/photos/"):
                return self._send_file(self.server.photos_dir, path[len("/photos/"):])
            if path.startswith("/cards/"):
                return self._send_file(self.server.cards_dir, path[len("/cards/"):])
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
                with self._db() as conn:
                    return self._send(200, plans_mod.get_plan(conn, _id_after(path, "/api/plans/")))
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
            with self._db() as conn:
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

    def _get_settings(self):
        with self._db() as conn:
            return self._send(200, _public_settings(core_settings.get_settings(conn)))

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
        saved = core_settings.update_settings(
            conn,
            table_name=_pick(body, "tableName", "table_name"),
            week_start_day=_pick(body, "weekStart", "week_start_day"),
            dinner_hour=_pick(body, "dinnerHour", "dinner_hour"),
            weather_location=_weather_location(body),
            now=self.server.now(),
        )
        return _public_settings(saved)
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
        if length < 0 or length > BODY_LIMIT:
            raise ValueError("Request too large or empty")
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
        self.wfile.write(body)


class _closing:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()
        return False

def _public_settings(raw: dict) -> dict:
    return {
        "tableName": raw["table_name"],
        "dinnerHour": raw["dinner_hour"],
        "weekStart": raw["week_start_day"],
        "weather": raw["weather"],
        "updatedAt": raw["updated_at"],
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
        "--origin",
        action="append",
        default=[],
        help="Allowed Origin for writes (repeatable). Same-host Origin is always allowed.",
    )
    args = parser.parse_args(argv)
    server = KitchenServer((args.host, args.port), args.db_path, origins=args.origin)
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
