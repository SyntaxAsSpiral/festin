"""Two devices over HTTP, each with its own cookie and its own turn."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from festin.schema import connect
from festin.server import COOKIE, KitchenServer


@pytest.fixture
def kitchen(tmp_path):
    server = KitchenServer(("127.0.0.1", 0), tmp_path / "store.sqlite")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


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


def test_a_held_turn_does_not_block_the_other_device(kitchen):
    port = kitchen.server_address[1]
    alice = Client(port)
    bram = Client(port)
    held = alice.put({"chat_id": "shared-chat", "turn": {"id": "turn-a", "phase": "thinking"}, "draft": "alice"})
    assert held[0] == 200
    other = bram.put({"chat_id": "shared-chat", "turn": {"id": "turn-b", "phase": "thinking"}, "draft": "bram"})
    assert other[0] == 200
    assert other[1]["turn"]["id"] == "turn-b"
    assert other[1]["draft"] == "bram"
    assert alice.get()[1]["turn"]["id"] == "turn-a"

    blocked = alice.put({"turn": {"id": "turn-c", "phase": "thinking"}})
    assert blocked[0] == 409
    switched = alice.put({"chat_id": "somewhere-else"})
    assert switched[0] == 409
    assert bram.put({"draft": "still bram"})[0] == 200
    assert bram.get()[1]["draft"] == "still bram"
    assert bram.get()[1]["turn"]["id"] == "turn-b"

    assert alice.put({"turn": None, "chat_id": "somewhere-else"})[0] == 200
    assert alice.get()[1]["turn"] is None
    assert alice.get()[1]["chat_id"] == "somewhere-else"


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
