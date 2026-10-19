"""/api/chat over real HTTP: NDJSON stream, per-chat lock, stop, errors, kitchen files."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from festin.chat.flights import clear_flights
from festin.schema import connect
from festin.server import COOKIE, KitchenServer
from festin.settings import update_settings
from tests.test_chat_engine import FakeCompleter


def reply(text):
    return {"message": {"role": "assistant", "content": text}}


@pytest.fixture
def kitchen(tmp_path):
    clear_flights()
    server = KitchenServer(("127.0.0.1", 0), tmp_path / "store.sqlite")
    conn = connect(server.db_path)
    update_settings(conn, model_name="test-model")
    conn.close()
    server.chat_options = {"model_key": "test-key"}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        clear_flights()


class Device:
    def __init__(self, server):
        self.port = server.server_address[1]
        self.cookie = None

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = f"{COOKIE}={self.cookie}"
        return headers

    def _keep_cookie(self, res):
        for value in res.headers.get_all("Set-Cookie") or []:
            name, _, rest = value.partition("=")
            if name == COOKIE:
                self.cookie = rest.split(";", 1)[0]

    def post(self, path, body):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, json.dumps(body), self._headers())
        res = conn.getresponse()
        self._keep_cookie(res)
        raw = res.read()
        conn.close()
        return res.status, res.getheader("Content-Type") or "", raw

    def chat(self, text, **extra):
        status, ctype, raw = self.post("/api/chat", {"text": text, **extra})
        if "ndjson" in ctype:
            return status, [json.loads(line) for line in raw.splitlines() if line.strip()]
        return status, json.loads(raw)

    def session(self, **changes):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        if changes:
            conn.request("PUT", "/api/session", json.dumps(changes), self._headers())
        else:
            conn.request("GET", "/api/session", headers=self._headers())
        res = conn.getresponse()
        self._keep_cookie(res)
        body = json.loads(res.read())
        conn.close()
        return res.status, body


def test_a_turn_streams_start_deltas_done(kitchen):
    kitchen.chat_options["completer"] = FakeCompleter([reply("Bonsoir. The pot is warm.")])
    status, events = Device(kitchen).chat("Hello")
    assert status == 200
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Bonsoir. The pot is warm."


def test_a_device_with_no_chat_gets_one_and_keeps_it(kitchen):
    kitchen.chat_options["completer"] = FakeCompleter([reply("one"), reply("two")])
    device = Device(kitchen)
    device.chat("first")
    _, before = device.session()
    assert before["chat_id"]
    device.chat("second")
    _, after = device.session()
    assert after["chat_id"] == before["chat_id"]


def test_first_chat_message_sets_the_chat_title(kitchen):
    kitchen.chat_options["completer"] = FakeCompleter([reply("Bonsoir."), reply("Encore.")])
    device = Device(kitchen)
    device.chat("What should we cook tonight?")
    _, session = device.session()
    chat_id = session["chat_id"]
    assert chat_id
    conn = connect(kitchen.db_path)
    try:
        row = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
        assert row["title"] == "What should we cook tonight?"
    finally:
        conn.close()
    device.chat("Something simpler")
    conn = connect(kitchen.db_path)
    try:
        row = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
        assert row["title"] == "What should we cook tonight?"
    finally:
        conn.close()


def test_two_devices_on_different_chats_answer_at_once(kitchen):
    kitchen.chat_options["completer"] = FakeCompleter([{"wait_cancel": True}, reply("meanwhile")])
    slow, quick = Device(kitchen), Device(kitchen)
    slow.session()
    results = {}
    worker = threading.Thread(target=lambda: results.update(slow=slow.chat("long one", submission_id="slow-turn-1")))
    worker.start()
    time.sleep(0.3)
    status, events = quick.chat("quick one")
    assert status == 200 and events[-1]["type"] == "done"
    slow.post("/api/stop", {"submission_id": "slow-turn-1"})
    worker.join(5)
    assert results["slow"][1][-1]["type"] == "stopped"


def test_a_second_device_on_the_same_chat_gets_409_until_the_turn_ends(kitchen):
    kitchen.chat_options["completer"] = FakeCompleter([{"wait_cancel": True}, reply("now it's free")])
    first, second = Device(kitchen), Device(kitchen)
    first.session(chat_id="shared-chat")
    second.session(chat_id="shared-chat")
    worker = threading.Thread(target=lambda: first.chat("hold it", submission_id="hold-turn-1"))
    worker.start()
    time.sleep(0.3)
    status, body = second.chat("me too")
    assert status == 409
    assert body["error"] == "Babette is answering this chat on another device."
    first.post("/api/stop", {"submission_id": "hold-turn-1"})
    worker.join(5)
    status, events = second.chat("me too", expected_messages=None)
    assert status == 200 and events[-1]["type"] == "done"


def test_a_refused_request_does_not_free_the_running_turn(kitchen):
    kitchen.chat_options["completer"] = FakeCompleter([{"wait_cancel": True}])
    device, other = Device(kitchen), Device(kitchen)
    device.session(chat_id="c1")
    other.session(chat_id="c1")
    worker = threading.Thread(target=lambda: device.chat("hold", submission_id="hold-turn-2"))
    worker.start()
    time.sleep(0.3)
    assert device.chat("again")[0] == 409  # same device, mid-turn
    assert other.chat("still held")[0] == 409  # the lock survived the refusal
    device.post("/api/stop", {"submission_id": "hold-turn-2"})
    worker.join(5)


def test_no_model_ends_the_stream_with_an_error_and_frees_the_chat(kitchen):
    conn = connect(kitchen.db_path)
    update_settings(conn, model_name="")
    conn.close()
    device = Device(kitchen)
    status, events = device.chat("hello")
    assert status == 200
    assert events[-1]["type"] == "error" and "Choose a model" in events[-1]["error"]
    _, session = device.session()
    assert session["turn"] is None


def test_an_empty_message_is_refused_in_the_stream(kitchen):
    status, events = Device(kitchen).chat("   ")
    assert events[-1] == {"type": "error", "error": "Write a message.", "status": 400}


def test_kitchen_files_are_served_and_paths_cannot_escape(kitchen, tmp_path):
    kitchen.photos_dir.mkdir(parents=True, exist_ok=True)
    (kitchen.photos_dir / "dish.jpg").write_bytes(b"\xff\xd8jpeg")
    (tmp_path / "secret.txt").write_text("no")
    port = kitchen.server_address[1]
    for path, want in (("/photos/dish.jpg", 200), ("/photos/..%2Fsecret.txt", 404), ("/photos/../secret.txt", 404), ("/cards/missing.jpg", 404)):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path)
        res = conn.getresponse()
        res.read()
        conn.close()
        assert res.status == want, path
