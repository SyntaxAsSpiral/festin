"""Two devices over HTTP, each with its own cookie and its own turn."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection

import pytest

from festin.schema import connect
from festin.server import COOKIE
from tests.conftest import reset_db_file, start_kitchen, stop_kitchen


@pytest.fixture(scope="module")
def _session_server(migrated_template, tmp_path_factory):
    root = tmp_path_factory.mktemp("session")
    db = root / "store.sqlite"
    shutil.copy2(migrated_template, db)
    server = start_kitchen(db)
    try:
        yield server, db, migrated_template
    finally:
        stop_kitchen(server)


@pytest.fixture
def kitchen(_session_server):
    server, db, template = _session_server
    reset_db_file(db, template)
    yield server


class Client:
    def __init__(self, port: int):
        self.port = port
        self.cookie = None

    def get(self):
        return self.request("GET", None)

    def put(self, body, *, cookie=None):
        return self.request("PUT", body, cookie=cookie)

    def request(self, method, body, *, cookie=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        sent = self.cookie if cookie is None else cookie
        if sent:
            headers["Cookie"] = f"{COOKIE}={sent}"
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(raw))
        conn.request(method, "/api/session", body=raw, headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        issued = _cookie_value(response.getheader("Set-Cookie"))
        if cookie is None and issued:
            self.cookie = issued
        conn.close()
        return response.status, payload, issued


def _cookie_value(header):
    if not header:
        return None
    first = header.split(";", 1)[0]
    name, _, value = first.partition("=")
    if name.strip() != COOKIE or not value:
        return None
    return value


def test_two_clients_get_different_cookies_and_sessions(kitchen):
    port = kitchen.server_address[1]
    first = Client(port).get()
    second = Client(port).get()
    assert first[0] == 200 and second[0] == 200
    assert first[2] and second[2]
    assert first[2] != second[2]
    assert first[1]["id"] != second[1]["id"]
    assert first[1]["id"] == first[2]
    assert second[1]["id"] == second[2]


def test_each_session_keeps_its_own_chat_and_draft(kitchen):
    port = kitchen.server_address[1]
    alice = Client(port)
    bram = Client(port)
    assert alice.put({"chat_id": "chat-alice", "draft": "salt the chicken", "pane": "meals", "surface": "peek"})[0] == 200
    assert bram.put({"chat_id": "chat-bram", "draft": "leave Thursday open", "pane": "recipes", "surface": "tucked"})[0] == 200
    alice_body = alice.get()[1]
    bram_body = bram.get()[1]
    assert alice_body["chat_id"] == "chat-alice"
    assert alice_body["draft"] == "salt the chicken"
    assert alice_body["pane"] == "meals"
    assert alice_body["surface"] == "peek"
    assert bram_body["chat_id"] == "chat-bram"
    assert bram_body["draft"] == "leave Thursday open"
    assert bram_body["surface"] == "tucked"


def test_a_turn_on_one_chat_does_not_block_another_chat(kitchen):
    port = kitchen.server_address[1]
    alice = Client(port)
    bram = Client(port)
    held = alice.put({"chat_id": "chat-a", "turn": {"id": "turn-a", "phase": "thinking"}, "draft": "alice"})
    assert held[0] == 200
    other = bram.put({"chat_id": "chat-b", "turn": {"id": "turn-b", "phase": "thinking"}, "draft": "bram"})
    assert other[0] == 200
    assert other[1]["turn"]["id"] == "turn-b"
    assert other[1]["chat_id"] == "chat-b"
    assert alice.get()[1]["turn"]["id"] == "turn-a"
    assert alice.get()[1]["chat_id"] == "chat-a"

    blocked = alice.put({"turn": {"id": "turn-c", "phase": "thinking"}})
    assert blocked[0] == 409
    assert blocked[1]["error"] == "This session is mid-turn."
    switched = alice.put({"chat_id": "somewhere-else"})
    assert switched[0] == 409
    assert bram.put({"draft": "still bram"})[0] == 200
    assert bram.get()[1]["turn"]["id"] == "turn-b"


def test_a_second_session_on_the_same_chat_gets_409(kitchen):
    port = kitchen.server_address[1]
    alice = Client(port)
    bram = Client(port)
    assert alice.put({"chat_id": "chat-a", "turn": {"id": "turn-a", "phase": "thinking"}})[0] == 200
    assert bram.put({"chat_id": "chat-a", "draft": "just looking"})[0] == 200
    blocked = bram.put({"turn": {"id": "turn-b", "phase": "thinking"}})
    assert blocked[0] == 409
    assert blocked[1]["error"] == "Babette is answering this chat on another device."
    assert alice.get()[1]["turn"]["id"] == "turn-a"
    assert bram.get()[1]["turn"] is None
    assert bram.get()[1]["draft"] == "just looking"


def test_clearing_a_turn_frees_its_chat(kitchen):
    port = kitchen.server_address[1]
    alice = Client(port)
    bram = Client(port)
    assert alice.put({"chat_id": "chat-a", "turn": {"id": "turn-a", "phase": "thinking"}})[0] == 200
    assert bram.put({"chat_id": "chat-a"})[0] == 200
    assert bram.put({"turn": {"id": "turn-b", "phase": "thinking"}})[0] == 409
    assert alice.put({"turn": None})[0] == 200
    assert alice.get()[1]["turn"] is None
    taken = bram.put({"turn": {"id": "turn-b", "phase": "thinking"}})
    assert taken[0] == 200
    assert taken[1]["turn"]["id"] == "turn-b"
    assert alice.get()[1]["turn"] is None


def test_a_stale_turn_expires(kitchen):
    start = datetime(2026, 10, 18, 18, 0, tzinfo=timezone.utc)
    kitchen.now = lambda: start
    port = kitchen.server_address[1]
    alice = Client(port)
    bram = Client(port)
    assert alice.put({"chat_id": "chat-a", "turn": {"id": "turn-a", "phase": "thinking"}})[0] == 200

    start = start + timedelta(minutes=9)
    still = bram.put({"chat_id": "chat-a", "turn": {"id": "turn-b", "phase": "thinking"}})
    assert still[0] == 409
    assert alice.get()[1]["turn"]["id"] == "turn-a"

    start = start + timedelta(minutes=1)
    taken = bram.put({"chat_id": "chat-a", "turn": {"id": "turn-b", "phase": "thinking"}})
    assert taken[0] == 200
    assert taken[1]["turn"]["id"] == "turn-b"
    assert alice.get()[1]["turn"] is None


def test_the_same_cookie_returns_the_same_session(kitchen):
    port = kitchen.server_address[1]
    client = Client(port)
    status, first, cookie = client.get()
    assert status == 200
    assert client.put({"chat_id": "chat-1", "draft": "half a thought"})[0] == 200
    again = Client(port)
    again.cookie = cookie
    status, body, issued = again.get()
    assert status == 200
    assert issued == cookie
    assert body["id"] == first["id"]
    assert body["chat_id"] == "chat-1"
    assert body["draft"] == "half a thought"


def test_a_forged_cookie_gets_a_new_session(kitchen):
    port = kitchen.server_address[1]
    forged = Client(port)
    status, body, issued = forged.request("GET", None, cookie="forged-token")
    assert status == 200
    assert body["id"] != "forged-token"
    assert issued != "forged-token"
    assert body["chat_id"] is None
    assert body["draft"] == ""
    conn = connect(kitchen.db_path)
    try:
        stolen = conn.execute("SELECT id FROM sessions WHERE id = 'forged-token'").fetchone()
        assert stolen is None
        real = conn.execute("SELECT id FROM sessions WHERE id = ?", (body["id"],)).fetchone()
        assert real is not None
    finally:
        conn.close()
    status, second, issued_again = forged.request("GET", None, cookie="forged-token")
    assert status == 200
    assert second["id"] != body["id"]
    assert issued_again != "forged-token"
