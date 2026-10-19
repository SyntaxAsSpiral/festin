"""Cloud agents outbound: destinations CRUD and send_list (local fake webhook only)."""

from __future__ import annotations

import json
import os
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from festin import notes
from festin.chat.engine import _ToolCtx
from festin.plugins import host
from festin.plugins.outbound import webhooks
from festin.schema import connect
from tests.conftest import start_kitchen, stop_kitchen


class Client:
    def __init__(self, port: int):
        self.port = port
        self.origin = "http://kitchen.example"

    def request(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Origin": self.origin}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(raw))
        elif method in ("POST", "PUT"):
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = "0"
            raw = b"{}"
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        payload = response.read()
        status = response.status
        conn.close()
        return status, json.loads(payload.decode() or "null")


def _outbound(plugins):
    return next(item for item in plugins if item["id"] == "outbound")


def _listen(captured):
    class Capture(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            captured.append(
                {
                    "body": json.loads(self.rfile.read(length)),
                    "authorization": self.headers.get("Authorization"),
                }
            )
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Capture)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def stop():
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()

    url = f"http://127.0.0.1:{httpd.server_port}/hook"
    return url, stop


def test_outbound_plugin_lists_and_tools_follow_the_switch(blank_db):
    server = start_kitchen(blank_db, origins=("http://kitchen.example",))
    client = Client(server.server_address[1])
    try:
        status, body = client.request("GET", "/api/plugins")
        assert status == 200
        ids = [item["id"] for item in body["plugins"]]
        assert ids == ["printer", "outbound"]
        plug = _outbound(body["plugins"])
        assert plug["enabled"] is False
        assert plug["name"] == "Cloud agents"
        assert plug["settings"]["defaultAgent"] == ""
        assert plug["settings"]["destinations"] == []
        dest_field = next(f for f in plug["schema"] if f["key"] == "destinations")
        assert dest_field["type"] == "agents"

        conn = connect(server.db_path)
        assert "send_list" not in host.build_registry(conn).names()

        status, saved = client.request("PUT", "/api/plugins/outbound", {"enabled": True})
        assert status == 200
        assert saved["enabled"] is True
        registry = host.build_registry(conn)
        assert "send_list" in registry.names()
        tools = {item["function"]["name"]: item["function"] for item in registry.openai_tools()}
        assert tools["send_list"]["parameters"]["required"] == ["list_name"]
        assert registry.tool_label("send_list") == "Sent a list"
        assert len(registry.names()) == 18

        status, off = client.request("PUT", "/api/plugins/outbound", {"enabled": False})
        assert status == 200
        assert "send_list" not in host.build_registry(conn).names()
        status, blocked = client.request(
            "POST", "/api/plugins/outbound/destinations", {"op": "add", "name": "x", "url": "http://127.0.0.1:9/"}
        )
        assert status == 404
        conn.close()
    finally:
        stop_kitchen(server)


def test_destinations_crud_and_default_over_http(blank_db):
    server = start_kitchen(blank_db, origins=("http://kitchen.example",))
    client = Client(server.server_address[1])
    secret = "scratch-destination-secret"
    try:
        client.request("PUT", "/api/plugins/outbound", {"enabled": True})

        leaked, leaked_body = client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {
                "op": "add",
                "name": "leaky",
                "url": "https://user:s3cret@example.com/hook",
                "auth_env": "SCRATCH_LIST_KEY",
            },
        )
        assert leaked == 400
        assert "s3cret" not in json.dumps(leaked_body)

        pasted, pasted_body = client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {
                "op": "add",
                "name": "pasted",
                "url": "https://example.invalid/hook",
                "auth_env": secret,
            },
        )
        assert pasted == 400
        assert secret not in json.dumps(pasted_body)

        other_status, _ = client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {"op": "add", "name": "other-agent", "url": "http://127.0.0.1:9/other", "auth_env": ""},
        )
        assert other_status == 200

        added, added_body = client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {
                "op": "add",
                "name": "chosen-agent",
                "url": "https://example.invalid/pending",
                "auth_env": "SCRATCH_LIST_KEY",
            },
        )
        assert added == 200
        assert secret not in json.dumps(added_body)

        edited, edited_body = client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {
                "op": "edit",
                "name": "chosen-agent",
                "new_name": "chosen-agent",
                "url": "http://127.0.0.1:9/chosen",
                "auth_env": "SCRATCH_LIST_KEY",
            },
        )
        assert edited == 200
        assert edited_body["destinations"]

        defaulted, view = client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {"op": "default", "name": "chosen-agent"},
        )
        assert defaulted == 200
        assert view["default"] == "chosen-agent"
        assert [(row["name"], row["auth_env"]) for row in view["destinations"]] == [
            ("other-agent", ""),
            ("chosen-agent", "SCRATCH_LIST_KEY"),
        ]
        assert secret not in json.dumps(view)

        status, listed = client.request("GET", "/api/plugins/outbound")
        assert status == 200
        assert listed["settings"]["defaultAgent"] == "chosen-agent"
        assert secret not in json.dumps(listed)
        assert "Bearer" not in json.dumps(listed)
    finally:
        stop_kitchen(server)


def test_send_list_posts_the_note_and_names_an_unknown_agent(blank_db, monkeypatch):
    server = start_kitchen(blank_db, origins=("http://kitchen.example",))
    client = Client(server.server_address[1])
    captured = []
    url, stop = _listen(captured)
    try:
        client.request("PUT", "/api/plugins/outbound", {"enabled": True})
        conn = connect(server.db_path)
        notes.create_note(
            conn,
            {"type": "shopping", "text": "milk\neggs\n1 onion, diced", "open": True},
        )

        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {"op": "add", "name": "grok-bot", "url": url, "auth_env": ""},
        )

        registry = host.build_registry(conn)
        ctx = _ToolCtx(conn, server.data_dir, "chat-1")
        result = registry.dispatch("send_list", {"list_name": "shopping", "agent": "grok-bot"}, ctx)
        note = {"from": "babette", "list": "shopping", "items": ["milk", "eggs", "1 onion, diced"]}
        assert captured == [{"body": note, "authorization": None}]
        assert result["status"] == "sent"
        assert result["agent"] == "grok-bot"

        try:
            registry.dispatch("send_list", {"list_name": "shopping", "agent": "muse"}, ctx)
            assert False, "expected unknown agent"
        except ValueError as exc:
            assert "Unknown agent" in str(exc)

        fixture = "fixture-webhook-key"
        previous = os.environ.get("GROKBOT_WEBHOOK_KEY")
        monkeypatch.setenv("GROKBOT_WEBHOOK_KEY", fixture)
        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {
                "op": "edit",
                "name": "grok-bot",
                "new_name": "grok-bot",
                "url": url,
                "auth_env": "GROKBOT_WEBHOOK_KEY",
            },
        )
        authed = registry.dispatch("send_list", {"list_name": "shopping", "agent": "grok-bot"}, ctx)
        assert authed["status"] == "sent"
        assert fixture not in json.dumps(authed)
        assert captured[1]["body"] == note
        assert captured[1]["authorization"] == "Bearer " + fixture

        monkeypatch.delenv("GROKBOT_WEBHOOK_KEY", raising=False)
        try:
            registry.dispatch("send_list", {"list_name": "shopping", "agent": "grok-bot"}, ctx)
            assert False, "expected missing env"
        except ValueError as exc:
            assert "GROKBOT_WEBHOOK_KEY" in str(exc)
            assert fixture not in str(exc)
        assert len(captured) == 2
        if previous is not None:
            os.environ["GROKBOT_WEBHOOK_KEY"] = previous
        conn.close()
    finally:
        stop()
        stop_kitchen(server)


def test_default_cloud_agent_is_the_only_destination_that_receives_the_list(blank_db, monkeypatch):
    server = start_kitchen(blank_db, origins=("http://kitchen.example",))
    client = Client(server.server_address[1])
    chosen_captured = []
    other_captured = []
    chosen_url, stop_chosen = _listen(chosen_captured)
    other_url, stop_other = _listen(other_captured)
    secret = "scratch-list-key-9f3a"
    try:
        client.request("PUT", "/api/plugins/outbound", {"enabled": True})
        conn = connect(server.db_path)
        notes.create_note(
            conn,
            {"type": "shopping", "text": "- milk\n- eggs\n- 1 onion, diced", "open": True},
        )
        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {"op": "add", "name": "other-agent", "url": other_url, "auth_env": ""},
        )
        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {
                "op": "add",
                "name": "chosen-agent",
                "url": chosen_url,
                "auth_env": "SCRATCH_LIST_KEY",
            },
        )
        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {"op": "default", "name": "chosen-agent"},
        )
        monkeypatch.setenv("SCRATCH_LIST_KEY", secret)
        registry = host.build_registry(conn)
        ctx = _ToolCtx(conn, server.data_dir, "chat-1")
        note = {"from": "babette", "list": "shopping", "items": ["milk", "eggs", "1 onion, diced"]}
        result = registry.dispatch("send_list", {"list_name": "shopping"}, ctx)
        assert result["status"] == "sent"
        assert result["agent"] == "chosen-agent"
        assert secret not in json.dumps(result)
        assert chosen_captured == [{"body": note, "authorization": "Bearer " + secret}]
        assert other_captured == []

        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {
                "op": "edit",
                "name": "chosen-agent",
                "new_name": "chosen-agent",
                "url": "http://127.0.0.1:9/closed",
                "auth_env": "SCRATCH_LIST_KEY",
            },
        )
        try:
            registry.dispatch("send_list", {"list_name": "shopping"}, ctx)
            assert False, "expected unreachable"
        except ValueError as exc:
            assert "could not be reached" in str(exc)
            assert secret not in str(exc)
        assert len(chosen_captured) == 1
        assert other_captured == []
        conn.close()
    finally:
        stop_chosen()
        stop_other()
        stop_kitchen(server)


def test_send_list_rejects_empty_and_missing_lists(blank_db):
    server = start_kitchen(blank_db, origins=("http://kitchen.example",))
    client = Client(server.server_address[1])
    captured = []
    url, stop = _listen(captured)
    try:
        client.request("PUT", "/api/plugins/outbound", {"enabled": True})
        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {"op": "add", "name": "grok-bot", "url": url},
        )
        client.request(
            "POST",
            "/api/plugins/outbound/destinations",
            {"op": "default", "name": "grok-bot"},
        )
        conn = connect(server.db_path)
        conn.execute(
            """
            INSERT INTO notes (
                id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
            ) VALUES ('empty-shop', 'shopping', '   \n\n', 'none', NULL, 1, '2026-10-19', NULL, NULL,
                      '2026-10-19T00:00:00.000000Z')
            """
        )
        conn.commit()
        registry = host.build_registry(conn)
        ctx = _ToolCtx(conn, server.data_dir, "chat-1")
        try:
            registry.dispatch("send_list", {"list_name": "shopping"}, ctx)
            assert False, "expected empty list"
        except ValueError as exc:
            assert "no items" in str(exc).casefold()
        try:
            registry.dispatch("send_list", {"list_name": "pantry"}, ctx)
            assert False, "expected missing note"
        except ValueError as exc:
            assert "No note named" in str(exc)
        assert captured == []
        conn.close()
    finally:
        stop()
        stop_kitchen(server)


def test_list_poster_hook_avoids_network(blank_db):
    """Unit path: injectable poster never opens a socket."""
    conn = connect(blank_db)
    host.update_plugin(conn, "outbound", {"enabled": True})
    webhooks.write_settings(
        conn,
        enabled=True,
        settings={
            "defaultAgent": "fake-bot",
            "destinations": [{"name": "fake-bot", "url": "http://127.0.0.1:9/unused", "auth_env": ""}],
        },
        stamp="2026-10-19T00:00:00.000000Z",
    )
    notes.create_note(conn, {"type": "shopping", "text": "butter", "open": True})
    seen = []

    def fake_poster(url, payload, auth_env):
        seen.append((url, payload, auth_env))
        return payload

    previous = webhooks.list_poster
    webhooks.list_poster = fake_poster
    try:
        result = webhooks.send_list(conn, {"list_name": "shopping list"})
        assert result["status"] == "sent"
        assert result["agent"] == "fake-bot"
        assert seen == [
            (
                "http://127.0.0.1:9/unused",
                {"from": "babette", "list": "shopping", "items": ["butter"]},
                None,
            )
        ]
    finally:
        webhooks.list_poster = previous
    conn.close()
