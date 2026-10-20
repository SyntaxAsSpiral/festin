"""Model settings over HTTP: URL, name, the 0600 key file, and a fake provider."""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from festin.chat.model_probe import BAD_KEY, NO_KEY, NO_TOOLS, NOT_FOUND, OK, UNREACHABLE
from festin.server import KitchenServer
from festin.settings import DEFAULT_MODEL_BASE_URL
from tests.conftest import reset_db_file, start_kitchen, stop_kitchen

SECRET = "sk-test-9f3a-do-not-echo"
GOOD = "sk-provider-good-7c1e"


@pytest.fixture(scope="module")
def _model_server(migrated_template, tmp_path_factory):
    root = tmp_path_factory.mktemp("model")
    db = root / "store.sqlite"
    shutil.copy2(migrated_template, db)
    server = start_kitchen(db, origins=("http://kitchen.example",))
    try:
        yield server, db, migrated_template, root
    finally:
        stop_kitchen(server)


@pytest.fixture
def kitchen(_model_server, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("FESTIN_MODEL_KEY", raising=False)
    server, db, template, root = _model_server
    reset_db_file(db, template)
    # Drop any prior key file next to the module DB.
    key_path = root / "model.key"
    if key_path.exists():
        key_path.unlink()
    yield server


class Client:
    def __init__(self, port: int):
        self.port = port
        self.origin = "http://kitchen.example"
        self.seen = []

    def request(self, method, path, body=None, *, origin=None, content_type="application/json"):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {}
        sent = self.origin if origin is None else origin
        if sent is not None:
            headers["Origin"] = sent
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            if content_type:
                headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(raw))
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        text = response.read().decode()
        self.seen.append(text)
        conn.close()
        return response.status, json.loads(text)


def test_model_url_name_and_key_file(kitchen):
    client = Client(kitchen.server_address[1])
    status, body = client.request("GET", "/api/settings")
    assert status == 200
    assert body["model"] == {
        "baseUrl": DEFAULT_MODEL_BASE_URL,
        "name": "",
        "keySet": False,
        "keySource": "none",
    }

    status, rejected = client.request(
        "POST",
        "/api/settings",
        {"modelBaseUrl": "https://user:secret@example.com/v1", "modelName": "nope"},
    )
    assert status == 400
    assert "HTTP(S)" in rejected["error"]

    status, saved = client.request(
        "POST",
        "/api/settings",
        {
            "modelName": "cook-model",
            "modelBaseUrl": "http://127.0.0.1:1234/v1/",
            "expectedUpdatedAt": body["updatedAt"],
        },
    )
    assert status == 200
    assert saved["model"]["baseUrl"] == "http://127.0.0.1:1234/v1"
    assert saved["model"]["name"] == "cook-model"
    assert saved["model"]["keySet"] is False
    assert saved["model"]["keySource"] == "none"
    assert saved["tableName"] == "Babette's Table"

    status, named = client.request("POST", "/api/settings", {"modelName": "other-model"})
    assert status == 200
    assert named["model"]["name"] == "other-model"
    assert named["model"]["baseUrl"] == "http://127.0.0.1:1234/v1"

    status, reset = client.request("POST", "/api/settings", {"modelBaseUrl": ""})
    assert status == 200
    assert reset["model"]["baseUrl"] == DEFAULT_MODEL_BASE_URL
    assert reset["model"]["name"] == "other-model"

    status, again = client.request("GET", "/api/settings")
    assert again["model"] == reset["model"]

    key_path = kitchen.data_dir / "model.key"
    status, stored = client.request("POST", "/api/settings/model-key", {"key": SECRET})
    assert status == 200
    assert stored["model"]["keySet"] is True
    assert stored["model"]["keySource"] == "file"
    assert stored["model"]["name"] == "other-model"
    assert key_path.read_text(encoding="utf-8") == SECRET
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    status, fetched = client.request("GET", "/api/settings")
    assert fetched["model"]["keySet"] is True
    assert fetched["model"]["keySource"] == "file"

    status, refused = client.request(
        "POST",
        "/api/settings/model-key",
        {"key": "should-not-land"},
        origin="http://evil.example",
    )
    assert status == 403
    assert key_path.read_text(encoding="utf-8") == SECRET

    status, broken = client.request("POST", "/api/settings/model-key", {"key": "one\ntwo"})
    assert status == 400
    assert key_path.read_text(encoding="utf-8") == SECRET

    status, cleared = client.request("POST", "/api/settings/model-key", {"key": ""})
    assert status == 200
    assert cleared["model"]["keySet"] is False
    assert cleared["model"]["keySource"] == "none"
    assert not key_path.exists()

    status, missing = client.request("POST", "/api/settings/model-key", {})
    assert status == 400

    blob = "\n".join(client.seen)
    assert SECRET not in blob
    assert "should-not-land" not in blob


def test_model_key_source_env(kitchen, monkeypatch):
    client = Client(kitchen.server_address[1])
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env-only-do-not-echo")
    status, body = client.request("GET", "/api/settings")
    assert status == 200
    assert body["model"]["keySet"] is False
    assert body["model"]["keySource"] == "env"
    assert "sk-env-only-do-not-echo" not in json.dumps(body)


def test_model_key_from_host_secret_file(kitchen, monkeypatch, tmp_path):
    from festin.chat.keys import resolve_model_key

    for name in ("OPENROUTER_API_KEY", "FESTIN_MODEL_KEY"):
        monkeypatch.delenv(name, raising=False)
    secret = tmp_path / "festin-model-key"
    secret.write_text("sk-secret-file-do-not-echo\n", encoding="utf-8")
    monkeypatch.setenv("FESTIN_MODEL_KEY_FILE", str(secret))
    assert resolve_model_key(tmp_path / "data", DEFAULT_MODEL_BASE_URL) == "sk-secret-file-do-not-echo"
    client = Client(kitchen.server_address[1])
    status, body = client.request("GET", "/api/settings")
    assert status == 200
    assert body["model"]["keySource"] == "env"
    assert "sk-secret-file-do-not-echo" not in json.dumps(body)
    # A missing secret file is no key, never an error.
    monkeypatch.setenv("FESTIN_MODEL_KEY_FILE", str(tmp_path / "absent"))
    assert resolve_model_key(tmp_path / "data", DEFAULT_MODEL_BASE_URL) == ""


class _Provider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _ok_auth(self) -> bool:
        return self.headers.get("Authorization") == "Bearer " + self.server.good_key

    def do_GET(self):
        self.server.hits += 1
        if not self.path.split("?", 1)[0].rstrip("/").endswith("/models"):
            self._send(404, {"error": {"message": "missing"}})
            return
        if not self._ok_auth():
            self._send(401, {"error": {"message": "invalid api key"}})
            return
        mode = self.server.mode
        if mode == "not_found":
            self._send(200, {"data": [{"id": "other", "supported_parameters": ["tools"]}]})
        elif mode == "no_tools":
            self._send(200, {"data": [{"id": "cook-model", "supported_parameters": ["temperature"]}]})
        elif mode == "ok":
            self._send(200, {"data": [{"id": "cook-model", "supported_parameters": ["tools"]}]})
        elif mode in ("completion_tools", "completion_ok"):
            self._send(200, {"data": [{"id": "cook-model"}]})
        else:
            self._send(500, {"error": {"message": "unknown mode"}})

    def do_POST(self):
        raw = self._body()
        self.server.hits += 1
        self.server.last_body = raw
        if not self._ok_auth():
            self._send(401, {"error": {"message": "invalid api key"}})
            return
        if self.server.mode == "completion_tools":
            self._send(400, {"error": {"message": "tools are not supported by this model"}})
            return
        self._send(200, {"choices": [{"message": {"content": "ok"}}]})


def _provider():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    server.good_key = GOOD
    server.mode = "ok"
    server.hits = 0
    server.last_body = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_model_test_reports_ok_and_each_failure(kitchen):
    provider = _provider()
    client = Client(kitchen.server_address[1])
    base = f"http://127.0.0.1:{provider.server_address[1]}/v1"
    try:
        status, saved = client.request(
            "POST",
            "/api/settings",
            {"modelName": "cook-model", "modelBaseUrl": base},
        )
        assert status == 200

        status, bare = client.request("POST", "/api/settings/model-test", {})
        assert status == 200
        assert bare == {"ok": False, "message": NO_KEY}
        assert provider.hits == 0

        client.request("POST", "/api/settings/model-key", {"key": "wrong-key"})
        status, bad = client.request("POST", "/api/settings/model-test", {})
        assert bad == {"ok": False, "message": BAD_KEY}

        client.request("POST", "/api/settings/model-key", {"key": GOOD})
        provider.mode = "not_found"
        status, missing = client.request("POST", "/api/settings/model-test", {})
        assert missing == {"ok": False, "message": NOT_FOUND}

        provider.mode = "no_tools"
        status, tools = client.request("POST", "/api/settings/model-test", {})
        assert tools == {"ok": False, "message": NO_TOOLS}

        provider.mode = "ok"
        before = provider.hits
        status, fine = client.request("POST", "/api/settings/model-test", {})
        assert fine == {"ok": True, "message": OK}
        assert provider.hits == before + 1

        provider.mode = "completion_tools"
        status, via_post = client.request("POST", "/api/settings/model-test", {})
        assert via_post == {"ok": False, "message": NO_TOOLS}
        posted = json.loads(provider.last_body)
        assert posted["max_tokens"] == 1
        assert posted["tools"][0]["function"]["name"] == "ping"
        assert GOOD not in provider.last_body.decode()

        provider.mode = "completion_ok"
        status, completed = client.request("POST", "/api/settings/model-test", {})
        assert completed == {"ok": True, "message": OK}

        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        closed_port = closed.getsockname()[1]
        closed.close()
        client.request(
            "POST",
            "/api/settings",
            {"modelBaseUrl": f"http://127.0.0.1:{closed_port}/v1", "modelName": "cook-model"},
        )
        status, down = client.request("POST", "/api/settings/model-test", {})
        assert down == {"ok": False, "message": UNREACHABLE}

        blob = "\n".join(client.seen)
        assert GOOD not in blob
        assert "wrong-key" not in blob
        assert SECRET not in blob
    finally:
        provider.shutdown()
        provider.server_close()


def test_key_file_mode_survives_umask(tmp_path):
    from festin.chat.keys import write_model_key

    old = os.umask(0o022)
    try:
        write_model_key(tmp_path, SECRET)
    finally:
        os.umask(old)
    path = tmp_path / "model.key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text(encoding="utf-8") == SECRET
