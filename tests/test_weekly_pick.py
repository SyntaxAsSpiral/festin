"""Babette's weekly pick: one model call per week for slip quote and plates (festin-3d6.26)."""

from __future__ import annotations

import json
import threading
import time
from datetime import date
from http.client import HTTPConnection

from festin.plugins import host
from festin.plugins.printer import printing, weekly
from festin.schema import apply, connect
from festin.server import KitchenServer
from festin.settings import update_settings

SAT = "2026-10-17"
PREV = "2026-10-10"
TODAY = date.fromisoformat(SAT)


def _plates():
    return {
        "top": "top-harvest",
        "bottom": "bottom-cake",
        "header": "header-rose",
        "pantry": "pantry-bay",
    }


def _valid_payload(**overrides):
    body = {
        "quote": "Pour la table et le feu.",
        "plates": _plates(),
    }
    body.update(overrides)
    return body


class FakePick:
    """Scripted structured completer for weekly pick (no network)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.messages = []

    def __call__(self, *, base, settings, key, messages, schema):
        self.calls += 1
        self.messages.append(messages)
        if not self.script:
            raise AssertionError("fake weekly pick exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class Client:
    def __init__(self, port: int):
        self.port = port
        self.origin = "http://kitchen.example"
        self.cookie = None

    def request(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Origin": self.origin}
        if self.cookie:
            headers["Cookie"] = self.cookie
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
        set_cookie = response.getheader("Set-Cookie")
        if set_cookie and "festin_session=" in set_cookie:
            self.cookie = set_cookie.split(";", 1)[0]
        conn.close()
        return status, json.loads(payload.decode() or "null")


def _kitchen(tmp_path):
    weekly.reset_attempts()
    server = KitchenServer(
        ("127.0.0.1", 0),
        tmp_path / "store.sqlite",
        origins=("http://kitchen.example",),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _enable_pick(conn, *, on=True, model="test-model"):
    update_settings(conn, model_name=model)
    host.update_plugin(
        conn,
        "printer",
        {
            "enabled": True,
            "settings": {
                "receiverUrl": "http://127.0.0.1:9",
                "weeklyPick": on,
            },
        },
    )


def _wait_calls(fake, n=1, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fake.calls >= n:
            return
        time.sleep(0.02)
    raise AssertionError(f"expected {n} calls, got {fake.calls}")


def _wait_stored(conn, week, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if printing.stored_week_quote(conn, week) and printing.stored_week_plates(conn, week):
            return
        time.sleep(0.02)
    raise AssertionError("week pick was not stored")


def test_weekly_pick_setting_defaults_off_and_round_trips(tmp_path):
    server = _kitchen(tmp_path)
    client = Client(server.server_address[1])
    try:
        status, body = client.request("GET", "/api/plugins")
        assert status == 200
        printer = next(p for p in body["plugins"] if p["id"] == "printer")
        assert printer["settings"]["weeklyPick"] is False
        field = next(f for f in printer["schema"] if f["key"] == "weeklyPick")
        assert field["type"] == "boolean"
        assert field["default"] is False
        assert field["label"] == "Babette's weekly pick"
        assert "one model call a week" in field["help"].lower()

        status, saved = client.request(
            "PUT",
            "/api/plugins/printer",
            {"enabled": True, "settings": {"weeklyPick": True}},
        )
        assert status == 200
        assert saved["settings"]["weeklyPick"] is True

        status, bad = client.request(
            "PUT",
            "/api/plugins/printer",
            {"settings": {"weeklyPick": "yes"}},
        )
        assert status == 400
    finally:
        server.shutdown()
        server.server_close()


def test_run_weekly_pick_stores_quote_and_plates(tmp_path):
    weekly.reset_attempts()
    db = tmp_path / "store.sqlite"
    data_dir = tmp_path
    conn = connect(db)
    apply(conn)
    _enable_pick(conn)
    fake = FakePick([_valid_payload()])
    result = weekly.run_weekly_pick(
        conn,
        data_dir=data_dir,
        week=SAT,
        today=TODAY,
        completer=fake,
        model_key="test-key",
    )
    assert result["stored"] is True
    assert result["quote"] == "Pour la table et le feu."
    assert printing.stored_week_quote(conn, SAT) == "Pour la table et le feu."
    assert printing.stored_week_plates(conn, SAT) == _plates()
    assert fake.calls == 1
    assert "Pour les dames" in json.dumps(fake.messages[0])
    conn.close()


def test_run_weekly_pick_skips_week_already_set(tmp_path):
    weekly.reset_attempts()
    db = tmp_path / "store.sqlite"
    conn = connect(db)
    apply(conn)
    _enable_pick(conn)
    printing.store_week_quote(conn, SAT, "Déjà choisi.")
    printing.store_week_plates(conn, SAT, _plates())
    conn.commit()
    fake = FakePick([_valid_payload(quote="Should not store.")])
    result = weekly.run_weekly_pick(
        conn,
        data_dir=tmp_path,
        week=SAT,
        today=TODAY,
        completer=fake,
        model_key="test-key",
    )
    assert result == {"stored": False, "reason": "already-set"}
    assert fake.calls == 0
    assert printing.stored_week_quote(conn, SAT) == "Déjà choisi."
    conn.close()


def test_run_weekly_pick_fills_only_the_missing_quote(tmp_path):
    # Imported weeks often carry plates already; the pick still writes the quote.
    weekly.reset_attempts()
    db = tmp_path / "store.sqlite"
    conn = connect(db)
    apply(conn)
    _enable_pick(conn)
    kept = dict(_plates())
    printing.store_week_plates(conn, SAT, kept)
    conn.commit()
    fake = FakePick([_valid_payload()])
    result = weekly.run_weekly_pick(
        conn, data_dir=tmp_path, week=SAT, today=TODAY, completer=fake, model_key="test-key"
    )
    assert result["stored"] is True
    assert printing.stored_week_quote(conn, SAT) == "Pour la table et le feu."
    assert printing.stored_week_plates(conn, SAT) == kept
    conn.close()


def test_run_weekly_pick_bad_response_leaves_fallbacks(tmp_path):
    weekly.reset_attempts()
    db = tmp_path / "store.sqlite"
    conn = connect(db)
    apply(conn)
    _enable_pick(conn)
    fake = FakePick(["not-json{"])
    try:
        weekly.run_weekly_pick(
            conn,
            data_dir=tmp_path,
            week=SAT,
            today=TODAY,
            completer=fake,
            model_key="test-key",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "invalid JSON" in str(exc)
    assert printing.stored_week_quote(conn, SAT) == ""
    assert printing.stored_week_plates(conn, SAT) is None
    assert fake.calls == 1
    conn.close()


def test_trigger_respects_toggle_and_runs_once(tmp_path):
    server = _kitchen(tmp_path)
    client = Client(server.server_address[1])
    fake = FakePick([_valid_payload(), _valid_payload(quote="Second call")])
    server.chat_options = {"weekly_pick_completer": fake}
    # Freeze household today via weather timezone-free path: monkeypatch today.
    real_today = weekly.core_settings.today

    def fixed_today(conn, *, now=None):
        return TODAY

    weekly.core_settings.today = fixed_today
    try:
        conn = connect(server.db_path)
        _enable_pick(conn, on=False)
        conn.close()

        status, _ = client.request("GET", "/api/session")
        assert status == 200
        time.sleep(0.15)
        assert fake.calls == 0

        conn = connect(server.db_path)
        _enable_pick(conn, on=True)
        conn.close()
        weekly.reset_attempts()

        status, _ = client.request("GET", "/api/session")
        assert status == 200
        _wait_calls(fake, 1)
        conn = connect(server.db_path)
        _wait_stored(conn, SAT)
        first_quote = printing.stored_week_quote(conn, SAT)
        assert first_quote == "Pour la table et le feu."
        conn.close()

        status, _ = client.request("GET", "/api/session")
        assert status == 200
        status, _ = client.request("GET", f"/api/plans/{SAT}")
        assert status == 200
        time.sleep(0.2)
        assert fake.calls == 1
    finally:
        weekly.core_settings.today = real_today
        server.shutdown()
        server.server_close()


def test_trigger_skips_other_week_plan(tmp_path):
    server = _kitchen(tmp_path)
    client = Client(server.server_address[1])
    fake = FakePick([_valid_payload()])
    server.chat_options = {"weekly_pick_completer": fake}
    real_today = weekly.core_settings.today
    weekly.core_settings.today = lambda conn, *, now=None: TODAY
    try:
        conn = connect(server.db_path)
        _enable_pick(conn, on=True)
        conn.close()
        next_week = "2026-10-24"
        status, _ = client.request("GET", f"/api/plans/{next_week}")
        assert status == 200
        time.sleep(0.15)
        assert fake.calls == 0
    finally:
        weekly.core_settings.today = real_today
        server.shutdown()
        server.server_close()


def test_accept_plates_rejects_last_week_repeat_in_pick(tmp_path):
    weekly.reset_attempts()
    db = tmp_path / "store.sqlite"
    conn = connect(db)
    apply(conn)
    _enable_pick(conn)
    last = _plates()
    printing.store_week_plates(conn, PREV, last)
    conn.commit()
    fake = FakePick([_valid_payload(plates=dict(last))])
    result = weekly.run_weekly_pick(
        conn,
        data_dir=tmp_path,
        week=SAT,
        today=TODAY,
        completer=fake,
        model_key="test-key",
    )
    assert result["stored"] is True
    assert result["plates"] != last
    assert result["plates"] == printing.accept_plates(last, SAT, last)
    conn.close()
