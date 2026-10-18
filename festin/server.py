"""Kitchen server for one device's session.

ThreadingHTTPServer, stdlib only. This process serves /api/session.
A cookie names the device. The row holds that device's chat, turn, pane,
surface and draft. The in-flight turn is the chat lock, and it belongs to
the session: another device never receives a 409 because this one is mid-turn.

Version 3 of the schema is reserved for settings. This module does not take it.
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from festin.schema import apply, connect

COOKIE = "festin_session"
SURFACES = frozenset({"tucked", "peek", "full"})
FIELDS = ("chat_id", "turn", "pane", "surface", "draft")
_GUARDS: dict[str, threading.Lock] = {}
_GUARDS_LOCK = threading.Lock()


class MidTurn(Exception):
    """This session already holds a different turn."""


class KitchenServer(ThreadingHTTPServer):
    def __init__(self, server_address, db_path):
        self.db_path = db_path
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
        if urlparse(self.path).path != "/api/session":
            return self._send(404, {"error": "Not found"})
        self._session(None)

    def do_PUT(self):
        if urlparse(self.path).path != "/api/session":
            return self._send(404, {"error": "Not found"})
        try:
            changes = _parse_changes(self._read_body())
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc) or "Bad session"})
        self._session(changes)

    def _session(self, changes):
        token = _cookie(self.headers.get("Cookie"))
        conn = connect(self.server.db_path)
        try:
            conn.execute("PRAGMA busy_timeout = 5000")
            row = _row_for_cookie(conn, token)
            if changes is None:
                body = _public(row)
                self._send(200, body, row["id"])
                return
            guard = _guard(row["id"])
            with guard:
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (row["id"],)).fetchone()
                try:
                    values = _apply_changes(row, changes)
                except MidTurn:
                    self._send(409, {"error": "This session is mid-turn."}, row["id"])
                    return
                now = _now()
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
                        now,
                        row["id"],
                    ),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (row["id"],)).fetchone()
            self._send(200, _public(row), row["id"])
        finally:
            conn.close()

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length < 0 or length > 100_000:
            raise ValueError("Session body is too large")
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


def _row_for_cookie(conn, token):
    row = None
    if token:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (token,)).fetchone()
    if row is not None:
        return row
    now = _now()
    new_id = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (id, draft, created_at, updated_at) VALUES (?, '', ?, ?)",
        (new_id, now, now),
    )
    conn.commit()
    return conn.execute("SELECT * FROM sessions WHERE id = ?", (new_id,)).fetchone()


def _apply_changes(row, changes: dict) -> dict:
    """Return the stored columns. A different turn on this same row is a 409."""
    current = json.loads(row["turn_json"]) if row["turn_json"] else None
    turn = current
    if "turn" in changes:
        turn = changes["turn"]
        if current and turn and current["id"] != turn["id"]:
            raise MidTurn()
    chat_id = row["chat_id"]
    if "chat_id" in changes:
        chat_id = changes["chat_id"]
        # A turn started in this same request may name its chat. A turn already
        # held may not move to another chat.
        still_held = turn if "turn" in changes else current
        if current and still_held and chat_id != row["chat_id"]:
            raise MidTurn()
    pane = changes["pane"] if "pane" in changes else row["pane"]
    surface = changes["surface"] if "surface" in changes else row["surface"]
    draft = changes["draft"] if "draft" in changes else row["draft"]
    return {
        "chat_id": chat_id,
        "turn_json": None if turn is None else json.dumps(turn, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "pane": pane,
        "surface": surface,
        "draft": draft,
    }


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


def _public(row) -> dict:
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "turn": json.loads(row["turn_json"]) if row["turn_json"] else None,
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m festin.server")
    parser.add_argument("db_path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = KitchenServer((args.host, args.port), args.db_path)
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
