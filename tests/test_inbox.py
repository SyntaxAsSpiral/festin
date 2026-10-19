"""Incoming-recipes inbox: auth, limits, provenance, toggle, GET contract."""

from __future__ import annotations

import json
import shutil
import socket
from http.client import HTTPConnection

import pytest

from festin import inbox as inbox_mod
from festin.schema import connect
from festin.server import KitchenServer
from tests.conftest import reset_db_file, start_kitchen, stop_kitchen


@pytest.fixture(scope="module")
def _inbox_server(migrated_template, tmp_path_factory):
    root = tmp_path_factory.mktemp("inbox")
    db = root / "store.sqlite"
    shutil.copy2(migrated_template, db)
    server = start_kitchen(
        db,
        origins=("http://kitchen.example",),
        inbox_port=0,
    )
    try:
        yield server, db, migrated_template
    finally:
        stop_kitchen(server)


@pytest.fixture
def kitchen(_inbox_server):
    server, db, template = _inbox_server
    reset_db_file(db, template)
    # Inbox listener follows settings; ensure it is up after a blank reset.
    if server.inbox_bound_port() is None:
        server.start_inbox()
    yield server


class KitchenClient:
    def __init__(self, port: int):
        self.port = port
        self.origin = "http://kitchen.example"

    def request(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Origin": self.origin}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(raw))
        elif method == "POST":
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = "0"
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        conn.close()
        return response.status, payload


class InboxClient:
    def __init__(self, port: int):
        self.port = port

    def request(
        self,
        method,
        path,
        body=None,
        *,
        key=None,
        agent="test-agent",
        accept=None,
        content_type="application/json",
        raw_body=None,
    ):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if key is not None:
            headers["Authorization"] = f"Bearer {key}"
        if agent is not None:
            headers["X-Agent-Name"] = agent
        if accept:
            headers["Accept"] = accept
        raw = raw_body
        if raw is None and body is not None:
            raw = json.dumps(body).encode()
        if raw is not None:
            if content_type:
                headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(raw))
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, response.getheader("Content-Type"), data


def _mint(kitchen) -> str:
    client = KitchenClient(kitchen.server_address[1])
    status, body = client.request("POST", "/api/settings/inbox-key", {})
    assert status == 200
    key = body["inboxKey"]["key"]
    assert key
    assert "inboxKey" in body
    assert body["inbox"]["keySet"] is True
    assert key not in json.dumps({"inbox": body["inbox"]})
    return key


def _recipe(**overrides):
    body = {
        "title": "Agent broth",
        "ingredients": ["water", "salt"],
        "method": "1. Simmer.\n2. Season.",
        "source": "https://example.com/broth",
    }
    body.update(overrides)
    return body


def test_get_instructions_text_and_json(kitchen):
    port = kitchen.inbox_bound_port()
    assert port is not None
    client = InboxClient(port)

    status, ctype, data = client.request("GET", "/", agent=None)
    assert status == 200
    assert "text/plain" in ctype
    text = data.decode()
    assert "POST /recipes" in text
    assert "X-Agent-Name" in text
    assert "one ingredient per line" in text.lower() or "One ingredient per line" in text

    status, ctype, data = client.request("GET", "/", agent=None, accept="application/json")
    assert status == 200
    assert "application/json" in ctype
    payload = json.loads(data.decode())
    assert payload["endpoints"]["POST /recipes"]
    assert payload["limits"]["bodyBytes"] == 64 * 1024
    assert payload["example"]["body"]["title"]


def test_auth_missing_wrong_and_right(kitchen):
    key = _mint(kitchen)
    client = InboxClient(kitchen.inbox_bound_port())

    status, _, data = client.request("POST", "/recipes", _recipe(), key=None)
    assert status == 401
    assert json.loads(data.decode())["error"] == "Unauthorized"

    status, _, data = client.request("POST", "/recipes", _recipe(), key="wrong-key")
    assert status == 401

    status, _, data = client.request("POST", "/recipes", _recipe(), key=key)
    assert status == 201
    body = json.loads(data.decode())
    assert body["id"].startswith("CBK-")
    assert body["provenance"] == "documented"
    assert body["needsPracticeReview"] is True


def test_agent_name_required(kitchen):
    key = _mint(kitchen)
    client = InboxClient(kitchen.inbox_bound_port())
    status, _, data = client.request("POST", "/recipes", _recipe(), key=key, agent=None)
    assert status == 400
    assert "X-Agent-Name" in json.loads(data.decode())["error"]


def test_field_and_size_limits(kitchen):
    key = _mint(kitchen)
    client = InboxClient(kitchen.inbox_bound_port())

    status, _, data = client.request(
        "POST", "/recipes", _recipe(title="x" * 201), key=key
    )
    assert status == 400

    status, _, data = client.request(
        "POST", "/recipes", _recipe(ingredients=["x" * 241]), key=key
    )
    assert status == 400

    status, _, data = client.request(
        "POST", "/recipes", _recipe(photos=["nope.jpg"]), key=key
    )
    assert status == 400
    assert "photos" in json.loads(data.decode())["error"]

    huge = json.dumps(_recipe(notes="n" * 70_000)).encode()
    assert len(huge) > 64 * 1024
    status, _, data = client.request(
        "POST", "/recipes", key=key, raw_body=huge, content_type="application/json"
    )
    assert status == 400


def test_ingredients_as_newline_string(kitchen):
    key = _mint(kitchen)
    client = InboxClient(kitchen.inbox_bound_port())
    status, _, data = client.request(
        "POST",
        "/recipes",
        _recipe(ingredients="water\nsalt\npepper"),
        key=key,
    )
    assert status == 201
    recipe_id = json.loads(data.decode())["id"]
    kitchen_client = KitchenClient(kitchen.server_address[1])
    status, recipe = kitchen_client.request("GET", f"/api/recipes/{recipe_id}")
    assert status == 200
    assert recipe["ingredients"] == ["water", "salt", "pepper"]


def test_provenance_needs_review_and_log(kitchen):
    key = _mint(kitchen)
    client = InboxClient(kitchen.inbox_bound_port())
    status, _, data = client.request(
        "POST",
        "/recipes",
        _recipe(),
        key=key,
        agent="grok-scout",
    )
    assert status == 201
    recipe_id = json.loads(data.decode())["id"]

    kitchen_client = KitchenClient(kitchen.server_address[1])
    status, recipe = kitchen_client.request("GET", f"/api/recipes/{recipe_id}")
    assert status == 200
    assert recipe["provenance"] == "documented"
    assert recipe["voice"] == "Web"
    assert recipe["needsPracticeReview"] is True
    assert recipe["category"] in (None, "")
    assert recipe["source"] == "https://example.com/broth"

    status, log = kitchen_client.request("GET", "/api/log")
    assert status == 200
    events = []
    for week in log.get("weeks") or []:
        events.extend(week.get("events") or [])
    # Log shape may nest differently; also check DB directly.
    conn = connect(kitchen.db_path)
    row = conn.execute(
        "SELECT kind, detail, ref_id FROM kitchen_log_events WHERE ref_id = ?",
        (recipe_id,),
    ).fetchone()
    conn.close()
    assert row["kind"] == "recipe_added"
    assert row["detail"] == "from grok-scout"


def test_toggle_off_closes_listener(kitchen):
    key = _mint(kitchen)
    port = kitchen.inbox_bound_port()
    assert port is not None
    client = KitchenClient(kitchen.server_address[1])

    status, body = client.request("GET", "/api/settings")
    assert body["inbox"]["enabled"] is True
    assert body["inbox"]["address"].endswith(f":{port}")

    status, saved = client.request("POST", "/api/settings", {"inboxEnabled": False})
    assert status == 200
    assert saved["inbox"]["enabled"] is False
    assert kitchen.inbox_bound_port() is None

    with pytest.raises(OSError):
        InboxClient(port).request("GET", "/", agent=None)

    status, saved = client.request("POST", "/api/settings", {"inboxEnabled": True})
    assert status == 200
    assert saved["inbox"]["enabled"] is True
    new_port = kitchen.inbox_bound_port()
    assert new_port is not None
    status, _, data = InboxClient(new_port).request("POST", "/recipes", _recipe(), key=key)
    assert status == 201


def test_rate_limit(kitchen, monkeypatch):
    key = _mint(kitchen)
    client = InboxClient(kitchen.inbox_bound_port())
    monkeypatch.setattr(inbox_mod, "RATE_LIMIT", 3)
    kitchen._inbox_httpd.rate_limiter = inbox_mod.RateLimiter()

    for i in range(3):
        status, _, _ = client.request(
            "POST", "/recipes", _recipe(title=f"Broth {i}"), key=key
        )
        assert status == 201
    status, _, data = client.request("POST", "/recipes", _recipe(title="Too many"), key=key)
    assert status == 429
    assert "Too many" in json.loads(data.decode())["error"]


def test_settings_never_echo_key(kitchen):
    key = _mint(kitchen)
    client = KitchenClient(kitchen.server_address[1])
    status, body = client.request("GET", "/api/settings")
    dumped = json.dumps(body)
    assert key not in dumped
    assert body["inbox"]["keySet"] is True
    assert "inboxKey" not in body


def test_hash_key_constant_compare():
    key = inbox_mod.mint_key()
    digest = inbox_mod.hash_key(key)
    assert inbox_mod.key_matches(key, digest)
    assert not inbox_mod.key_matches(key + "x", digest)
    assert not inbox_mod.key_matches("", digest)


def test_public_inbox_url_is_shown_to_settings_and_agents(blank_db):
    server = KitchenServer(
        ("127.0.0.1", 0),
        blank_db,
        inbox_port=0,
        inbox_url="https://kitchen.example.net:8443/",
    )
    try:
        assert server.inbox_address() == "https://kitchen.example.net:8443"
        assert server._inbox_httpd.public_address == "https://kitchen.example.net:8443"
    finally:
        server.server_close()


def test_plain_instructions_show_the_public_address(blank_db):
    server = KitchenServer(
        ("127.0.0.1", 0), blank_db, inbox_port=0, inbox_url="https://kitchen.example.net:8443"
    )
    try:
        conn = HTTPConnection("127.0.0.1", server.inbox_bound_port(), timeout=5)
        conn.request("GET", "/")
        text = conn.getresponse().read().decode()
        assert "https://kitchen.example.net:8443/recipes" in text
        assert "127.0.0.1" not in text
    finally:
        server.server_close()
