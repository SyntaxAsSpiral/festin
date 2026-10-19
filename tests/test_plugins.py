"""Plugin host and the printer: HTTP switches, tools only when on, one print."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from festin import plans, recipes
from festin.chat.messages import ensure_chat
from festin.plugins import host
from festin.plugins.printer.printing import DEFAULT_SLIP_QUOTE
from festin.plugins.printer.slips import SLIP_SENTENCE
from festin.schema import WEEKDAYS, connect
from festin.server import KitchenServer

SAT = "2026-10-17"


class Ctx:
    def __init__(self, conn, data_dir, chat_id="chat-1"):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.chat_id = chat_id


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
        if path.startswith("/slips/"):
            return status, payload
        return status, json.loads(payload.decode() or "null")


def _kitchen(tmp_path):
    server = KitchenServer(
        ("127.0.0.1", 0),
        tmp_path / "store.sqlite",
        origins=("http://kitchen.example",),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _printer(plugins):
    return next(item for item in plugins if item["id"] == "printer")


def test_plugins_over_http_and_tools_follow_the_switch(tmp_path):
    server = _kitchen(tmp_path)
    client = Client(server.server_address[1])
    try:
        status, body = client.request("GET", "/api/plugins")
        assert status == 200
        printer = _printer(body["plugins"])
        assert printer["enabled"] is False
        assert printer["settings"]["receiverUrl"] == ""
        assert printer["settings"]["band"] == "babette"
        assert printer["name"] == "Thermal printer"
        band_field = next(f for f in printer["schema"] if f["key"] == "band")
        assert band_field["default"] == "babette"
        assert band_field["enum"][0] == "babette"
        assert "Dinner slips keep their own weekly plates" in (band_field.get("help") or "")


        status, weather = client.request("GET", "/api/weather")
        assert status == 200
        assert weather["status"] == "not configured"
        status, settings = client.request("GET", "/api/settings")
        assert status == 200
        assert "weather" in settings

        status, missing = client.request("POST", "/api/plugins/printer/print", {"slip_id": "nope"})
        assert status == 404

        conn = connect(server.db_path)
        assert "prepare_slip" not in host.build_registry(conn).names()
        assert "print_slip" not in host.build_registry(conn).names()

        status, saved = client.request(
            "PUT",
            "/api/plugins/printer",
            {"enabled": True, "settings": {"receiverUrl": "http://127.0.0.1:9", "band": "rose"}},
        )
        assert status == 200
        assert saved["enabled"] is True
        assert saved["settings"]["receiverUrl"] == "http://127.0.0.1:9"
        assert saved["settings"]["band"] == "rose"
        assert "token" not in saved["settings"]
        assert saved["settings"]["tokenSet"] is False
        token_field = next(f for f in saved["schema"] if f["key"] == "token")
        assert token_field.get("secret") is True

        status, bad = client.request(
            "PUT", "/api/plugins/printer", {"settings": {"receiverUrl": "192.168.1.50"}}
        )
        assert status == 400

        registry = host.build_registry(conn)
        tools = {item["function"]["name"]: item["function"] for item in registry.openai_tools()}
        assert "prepare_slip" in tools
        assert "print_slip" in tools
        assert SLIP_SENTENCE in tools["prepare_slip"]["description"]
        assert SLIP_SENTENCE in tools["print_slip"]["description"]
        assert tools["print_slip"]["parameters"]["required"] == ["slip_id"]
        assert tools["prepare_slip"]["parameters"]["properties"]["kind"]["enum"] == [
            "plan",
            "recipe",
            "note",
        ]
        assert registry.tool_label("prepare_slip") == "Prepared a slip"
        assert registry.tool_label("print_slip") == "Sent to the printer"
        assert len(registry.names()) == 18

        status, dinner = client.request("POST", "/api/plugins/printer/print-dinner", {})
        assert status == 400
        assert "weekStart" in dinner["error"]
        status, recipe_print = client.request(
            "POST", "/api/plugins/printer/print-recipe", {"recipe_id": "CBK-missing"}
        )
        assert status == 400

        status, feed = client.request("GET", "/api/plugins/printer/feed")
        assert status == 200
        assert {row["id"] for row in feed["bands"]} == {"scroll", "bay", "rose", "wheat", "rosemary"}

        status, off = client.request("PUT", "/api/plugins/printer", {"enabled": False})
        assert status == 200
        assert off["enabled"] is False
        assert off["settings"]["receiverUrl"] == "http://127.0.0.1:9"
        assert "token" not in off["settings"]
        assert "prepare_slip" not in host.build_registry(conn).names()
        status, blocked = client.request("POST", "/api/plugins/printer/print", {"slip_id": "nope"})
        assert status == 404
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_printer_token_never_echoed_and_put_keeps_it(tmp_path):
    server = _kitchen(tmp_path)
    client = Client(server.server_address[1])
    secret = "print-token-never-echo-9f3a"
    try:
        status, saved = client.request(
            "PUT",
            "/api/plugins/printer",
            {
                "enabled": True,
                "settings": {
                    "receiverUrl": "http://127.0.0.1:9",
                    "token": secret,
                    "band": "scroll",
                },
            },
        )
        assert status == 200
        assert saved["settings"]["tokenSet"] is True
        assert "token" not in saved["settings"]
        assert secret not in json.dumps(saved)

        status, listed = client.request("GET", "/api/plugins")
        assert status == 200
        printer = _printer(listed["plugins"])
        assert printer["settings"]["tokenSet"] is True
        assert "token" not in printer["settings"]
        assert secret not in json.dumps(listed)

        status, one = client.request("GET", "/api/plugins/printer")
        assert status == 200
        assert one["settings"]["tokenSet"] is True
        assert "token" not in one["settings"]
        assert secret not in json.dumps(one)

        status, kept = client.request(
            "PUT",
            "/api/plugins/printer",
            {"settings": {"receiverUrl": "http://127.0.0.1:9", "band": "rose", "token": ""}},
        )
        assert status == 200
        assert kept["settings"]["band"] == "rose"
        assert kept["settings"]["tokenSet"] is True
        assert "token" not in kept["settings"]

        conn = connect(server.db_path)
        stored = json.loads(
            conn.execute(
                "SELECT settings_json FROM plugin_settings WHERE plugin_id = 'printer'"
            ).fetchone()["settings_json"]
        )
        assert stored["token"] == secret
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def _enable(conn, url, token):
    host.update_plugin(
        conn,
        "printer",
        {"enabled": True, "settings": {"receiverUrl": url, "token": token, "band": "scroll"}},
    )


def _png(path: Path):
    with Image.open(path) as im:
        assert im.format == "PNG"
        assert im.mode == "L"
        assert im.width == 576
        assert im.height > 80


def test_prepare_slip_renders_recipe_note_and_week(tmp_path):
    server = _kitchen(tmp_path)
    try:
        conn = connect(server.db_path)
        _enable(conn, "http://127.0.0.1:9", "test-token")
        ensure_chat(conn, "chat-1")
        recipe = recipes.create_recipe(
            conn,
            {
                "title": "Honey bread",
                "category": "breads",
                "ingredients": ["flour", "honey"],
                "method": "Bake at 350 F for 20 minutes.",
                "voice": "house",
                "stub": False,
            },
        )
        days = [
            {
                "day": day,
                "recipe": None,
                "title": "Lentil soup" if day == "sat" else "",
                "ingredients": ["lentils"] if day == "sat" else [],
            }
            for day in WEEKDAYS
        ]
        plans.save_plan(conn, SAT, {"weekStart": SAT, "days": days})
        registry = host.build_registry(conn)
        ctx = Ctx(conn, server.data_dir)

        recipe_slip = registry.dispatch(
            "prepare_slip", {"kind": "recipe", "recipe_id": recipe["id"]}, ctx
        )
        note_slip = registry.dispatch(
            "prepare_slip",
            {"kind": "note", "title": "Market", "text": "Buy leeks."},
            ctx,
        )
        week_slip = registry.dispatch(
            "prepare_slip", {"kind": "plan", "week_start": SAT}, ctx
        )

        for slip, needle in (
            (recipe_slip, "Honey bread"),
            (note_slip, "Market"),
            (week_slip, "Lentil soup"),
        ):
            assert slip["status"] == "ready"
            assert needle in slip["rendered_text"]
            _png(server.data_dir / "slips" / f"{slip['slip_id']}.png")
        assert "flour" in recipe_slip["rendered_text"]
        assert "Buy leeks." in note_slip["rendered_text"]
        assert "sat: Lentil soup" in week_slip["rendered_text"]
        assert DEFAULT_SLIP_QUOTE in week_slip["rendered_text"]
        assert week_slip["ingredients"] == ["lentils"]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


class _Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode())
        self.server.posts.append(
            {"path": self.path, "auth": self.headers.get("Authorization"), "body": payload}
        )
        if self.headers.get("Authorization") != "Bearer test-token":
            self.send_response(401)
            self.end_headers()
            return
        status = "uncertain" if payload["slip_id"] in self.server.uncertain else "printed"
        raw = json.dumps({"status": status}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        return


def test_print_slip_posts_once_and_reports_uncertain(tmp_path):
    receiver = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
    receiver.posts = []
    receiver.uncertain = set()
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    server = _kitchen(tmp_path)
    try:
        conn = connect(server.db_path)
        port = receiver.server_address[1]
        _enable(conn, f"http://127.0.0.1:{port}", "test-token")
        ensure_chat(conn, "chat-1")
        registry = host.build_registry(conn)
        ctx = Ctx(conn, server.data_dir)
        first = registry.dispatch(
            "prepare_slip", {"kind": "note", "title": "One", "text": "A single copy."}, ctx
        )
        second = registry.dispatch(
            "prepare_slip", {"kind": "note", "title": "Two", "text": "The line went quiet."}, ctx
        )
        receiver.uncertain.add(second["slip_id"])

        printed = registry.dispatch("print_slip", {"slip_id": first["slip_id"]}, ctx)
        assert printed == {
            "slip_id": first["slip_id"],
            "status": "printed",
            "message": "Printed.",
        }
        again = registry.dispatch("print_slip", {"slip_id": first["slip_id"]}, ctx)
        assert again["status"] == "printed"
        assert again["message"] == "No additional print sent."

        unsure = registry.dispatch("print_slip", {"slip_id": second["slip_id"]}, ctx)
        assert unsure["status"] == "uncertain"
        assert "printer did not confirm" in unsure["message"]
        held = registry.dispatch("print_slip", {"slip_id": second["slip_id"]}, ctx)
        assert held["status"] == "uncertain"
        assert held["message"] == "No additional print sent."

        by_slip = {}
        for post in receiver.posts:
            assert post["path"] == "/print"
            assert post["auth"] == "Bearer test-token"
            body = post["body"]
            assert body["source"] == "festin"
            assert body["job_id"] == body["slip_id"]
            by_slip.setdefault(body["slip_id"], []).append(body)
        assert list(by_slip) == [first["slip_id"], second["slip_id"]]
        assert len(by_slip[first["slip_id"]]) == 1
        assert len(by_slip[second["slip_id"]]) == 1
        digest = by_slip[first["slip_id"]][0]["sha256"]
        assert digest == first["sha256"]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        receiver.shutdown()
        receiver.server_close()


def _plan_days():
    return [
        {
            "day": day,
            "recipe": None,
            "title": "Lentil soup" if day == "sat" else "",
            "ingredients": ["lentils"] if day == "sat" else [],
        }
        for day in WEEKDAYS
    ]


def test_print_dinner_and_test_slip_over_http_with_fake_receiver(tmp_path):
    receiver = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
    receiver.posts = []
    receiver.uncertain = set()
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    server = _kitchen(tmp_path)
    client = Client(server.server_address[1])
    try:
        port = receiver.server_address[1]
        url = f"http://127.0.0.1:{port}"
        status, enabled = client.request(
            "PUT",
            "/api/plugins/printer",
            {"enabled": True, "settings": {"receiverUrl": url, "token": "test-token", "band": "scroll"}},
        )
        assert status == 200
        assert enabled["settings"]["tokenSet"] is True
        assert "token" not in enabled["settings"]

        conn = connect(server.db_path)
        plans.save_plan(conn, SAT, {"weekStart": SAT, "days": _plan_days()})
        conn.close()

        status, first = client.request(
            "POST",
            "/api/plugins/printer/print-dinner",
            {"weekStart": SAT},
        )
        assert status == 200
        assert first["status"] == "printed"
        assert first["message"] == "Printed."
        assert len(receiver.posts) == 1

        status, again = client.request(
            "POST",
            "/api/plugins/printer/print-dinner",
            {"weekStart": SAT},
        )
        assert status == 200
        assert again["status"] == "printed"
        assert again["message"] == "No additional print sent."
        assert again["slip_id"] == first["slip_id"]
        assert len(receiver.posts) == 1

        status, test = client.request("POST", "/api/plugins/printer/test-slip", {})
        assert status == 200
        assert test["status"] == "printed"
        assert len(receiver.posts) == 2
        assert "Babette" in json.dumps(test) or test["status"] == "printed"

        # The Print button sends only the open card's ID; it prints the recipe as saved.
        status, made = client.request(
            "POST", "/api/recipes", {"title": "Venison Stroganoff", "ingredients": ["venison"], "method": "Sear."}
        )
        assert status in (200, 201)
        made = made.get("recipe", made)
        status, printed = client.request("POST", "/api/plugins/printer/print-recipe", {"recipe_id": made["id"]})
        assert status == 200
        assert printed["status"] == "printed"
        assert len(receiver.posts) == 3

        status, bare = client.request(
            "PUT",
            "/api/plugins/printer",
            {"settings": {"receiverUrl": url, "token": ""}},
        )
        assert status == 200
        assert bare["settings"]["tokenSet"] is True

        # Empty token on PUT keeps the stored value; clear in the DB for the error path.
        conn = connect(server.db_path)
        conn.execute(
            "UPDATE plugin_settings SET settings_json = ? WHERE plugin_id = 'printer'",
            (
                json.dumps(
                    {"receiverUrl": url, "token": "", "band": "scroll"},
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
        conn.close()

        status, missing = client.request("POST", "/api/plugins/printer/test-slip", {})
        assert status == 400
        assert "not set" in missing["error"].lower()
        assert len(receiver.posts) == 3
    finally:
        server.shutdown()
        server.server_close()
        receiver.shutdown()
        receiver.server_close()
