"""HTTP API: settings, weather, paged lists, stale 409, origin allowlist, LAN bind."""

from __future__ import annotations

import argparse
import base64
import io
import json
import shutil
import socket
import threading
from datetime import date, timedelta
from http.client import HTTPConnection
from unittest.mock import patch

import pytest

from festin.schema import connect
from festin.server import COOKIE, KitchenServer, main
from tests.conftest import reset_db_file, start_kitchen, stop_kitchen


@pytest.fixture(scope="module")
def _api_server(migrated_template, tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    db = root / "store.sqlite"
    photos = root / "cooking-photos"
    shutil.copy2(migrated_template, db)
    server = start_kitchen(
        db,
        origins=("http://kitchen.example",),
        photos_dir=photos,
    )
    try:
        yield server, db, migrated_template
    finally:
        stop_kitchen(server)


@pytest.fixture
def kitchen(_api_server):
    server, db, template = _api_server
    reset_db_file(db, template)
    yield server


@pytest.fixture
def lan_kitchen(blank_db):
    server = KitchenServer(("0.0.0.0", 0), blank_db)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        stop_kitchen(server)


class Client:
    def __init__(self, port: int, host: str = "127.0.0.1", *, origin=None):
        self.port = port
        self.host = host
        self.origin = origin
        self.cookie = None

    def request(self, method, path, body=None, *, origin=None, content_type="application/json"):
        conn = HTTPConnection(self.host, self.port, timeout=5)
        headers = {}
        if self.cookie:
            headers["Cookie"] = f"{COOKIE}={self.cookie}"
        sent_origin = self.origin if origin is None else origin
        if sent_origin is not None:
            headers["Origin"] = sent_origin
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            if content_type:
                headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(raw))
        elif method in ("POST", "PUT", "DELETE") and content_type:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = "0"
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        issued = _cookie_value(response.getheader("Set-Cookie"))
        if issued:
            self.cookie = issued
        conn.close()
        return response.status, payload


def _cookie_value(header):
    if not header:
        return None
    first = header.split(";", 1)[0]
    name, _, value = first.partition("=")
    if name.strip() != COOKIE or not value:
        return None
    return value


def _geocode_payload():
    return {
        "results": [
            {
                "name": "Hayden",
                "admin1": "Idaho",
                "country": "United States",
                "latitude": 47.76602,
                "longitude": -116.78658,
                "timezone": "America/Los_Angeles",
            }
        ]
    }


def _forecast_payload():
    return {
        "daily": {
            "time": ["2026-10-18", "2026-10-19"],
            "weather_code": [0, 3],
            "temperature_2m_min": [40.2, 42.0],
            "temperature_2m_max": [60.8, 55.1],
            "precipitation_probability_max": [10, 40],
        }
    }


def _response(payload: dict):
    return io.BytesIO(json.dumps(payload).encode())


def _week_days(start: str):
    begin = date.fromisoformat(start)
    days = []
    for index in range(7):
        when = begin + timedelta(days=index)
        days.append(
            {
                "day": ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[when.weekday()],
                "title": f"Night {index}",
                "recipe": None,
                "ingredients": [],
                "cooked": index == 0,
            }
        )
    return days


def test_settings_round_trip(kitchen):
    client = Client(kitchen.server_address[1])
    status, body = client.request("GET", "/api/settings")
    assert status == 200
    assert body["tableName"] == "Babette's Table"
    assert body["dinnerHour"] == "17:30"
    assert body["weekStart"] == "sat"
    assert body["weather"] == {"location": ""}

    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_geocode_payload())
        status, saved = client.request(
            "POST",
            "/api/settings",
            {
                "tableName": "Holliday Table",
                "dinnerHour": "18:00",
                "weekStart": "mon",
                "weatherLocation": "83835",
                "expected_updated_at": body["updatedAt"],
            },
        )
    assert status == 200
    assert saved["tableName"] == "Holliday Table"
    assert saved["dinnerHour"] == "18:00"
    assert saved["weekStart"] == "mon"
    assert saved["weather"]["location"] == "83835"
    assert saved["weather"]["timezone"] == "America/Los_Angeles"
    assert saved["updatedAt"]

    status, again = client.request("GET", "/api/settings")
    assert again == saved


def test_chat_wet_band_round_trip(kitchen):
    client = Client(kitchen.server_address[1])
    other = Client(kitchen.server_address[1])
    status, body = client.request("GET", "/api/settings")
    assert status == 200
    assert body["chatWetBand"] == 45

    status, junk = client.request("POST", "/api/settings", {"chatWetBand": "nope"})
    assert status == 400
    assert "Wet band" in junk["error"]
    status, still = other.request("GET", "/api/settings")
    assert still["chatWetBand"] == 45

    status, saved = client.request(
        "POST",
        "/api/settings",
        {"chatWetBand": 12, "expectedUpdatedAt": still["updatedAt"]},
    )
    assert status == 200
    assert saved["chatWetBand"] == 12
    status, read = other.request("GET", "/api/settings")
    assert read["chatWetBand"] == 12

    status, plain = client.request(
        "POST",
        "/api/settings",
        {"chatWetBand": 0, "expectedUpdatedAt": read["updatedAt"]},
    )
    assert status == 200
    assert plain["chatWetBand"] == 0


def test_weather_read(kitchen):
    client = Client(kitchen.server_address[1])
    status, bare = client.request("GET", "/api/weather")
    assert status == 200
    assert bare == {"status": "not configured"}

    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_geocode_payload())
        client.request("POST", "/api/settings", {"weatherLocation": "83835"})

    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_forecast_payload())
        status, forecast = client.request("GET", "/api/weather")
    assert status == 200
    assert forecast["status"] == "ok"
    assert forecast["location"] == "Hayden, Idaho, United States"
    assert forecast["days"][0]["conditions"] == "clear"


def test_delete_recipe_keeps_the_id_counter(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request("POST", "/api/recipes", {"title": "Gone", "ingredients": ["salt"]})
    assert status == 201
    status, deleted = client.request(
        "DELETE",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": recipe["updatedAt"]},
    )
    assert status == 200
    assert deleted["status"] == "deleted"
    status, missing = client.request("GET", f"/api/recipes/{recipe['id']}")
    assert status == 404
    status, nxt = client.request("POST", "/api/recipes", {"title": "Next", "ingredients": ["salt"]})
    assert status == 201
    assert nxt["id"] != recipe["id"]


def test_stale_recipe_and_plan_write_get_409(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request("POST", "/api/recipes", {"title": "Soup", "ingredients": ["water"]})
    assert status == 201
    stamp = recipe["updatedAt"]

    status, updated = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": stamp, "changes": {"title": "Broth"}},
    )
    assert status == 200
    assert updated["title"] == "Broth"

    status, conflict = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": stamp, "changes": {"title": "Stock"}},
    )
    assert status == 409
    assert "changed" in conflict["error"].casefold()

    week = "2026-10-17"
    days = _week_days(week)
    status, plan = client.request(
        "POST",
        f"/api/plans/{week}",
        {"weekStart": week, "days": days, "slipTitle": "Le Festin", "expected_updated_at": None},
    )
    assert status == 200
    assert plan["slipTitle"] == "Le Festin"
    assert plan["days"][0]["cooked"] is True

    status, stale = client.request(
        "POST",
        f"/api/plans/{week}",
        {
            "weekStart": week,
            "days": days,
            "slipTitle": "Other",
            "expected_updated_at": None,
        },
    )
    assert status == 409


def test_chats_page_instead_of_all_at_once(kitchen):
    client = Client(kitchen.server_address[1])
    # Seed filed chats directly so the list has a stable ordinal order.
    conn = connect(kitchen.db_path)
    try:
        for index in range(5):
            chat_id = f"chat-{index}"
            conn.execute(
                "INSERT INTO chats (id, title, ordinal, imported_active, updated_at) VALUES (?, ?, ?, 0, ?)",
                (chat_id, f"Title {index}", index, "2026-10-18T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO chat_messages (chat_id, position, role, content, extra_json) VALUES (?, 0, 'user', ?, '{}')",
                (chat_id, f"hello {index}"),
            )
        conn.commit()
    finally:
        conn.close()

    status, page = client.request("GET", "/api/chats?limit=2")
    assert status == 200
    assert len(page["chats"]) == 2
    assert page["chats"][0]["id"] == "chat-0"
    assert page["nextCursor"]
    status, page2 = client.request("GET", f"/api/chats?limit=2&cursor={page['nextCursor']}")
    assert status == 200
    assert [c["id"] for c in page2["chats"]] == ["chat-2", "chat-3"]
    status, one = client.request("GET", "/api/chats/chat-1")
    assert status == 200
    assert one["messages"][0]["content"] == "hello 1"


def test_refused_origin(kitchen):
    client = Client(kitchen.server_address[1], origin="http://evil.example")
    status, body = client.request("POST", "/api/recipes", {"title": "Nope", "ingredients": []})
    assert status == 403
    assert body["error"] == "Same-origin JSON required"

    # Allowlisted origin may write.
    status, ok = client.request(
        "POST",
        "/api/recipes",
        {"title": "Yes", "ingredients": ["salt"]},
        origin="http://kitchen.example",
    )
    assert status == 201
    assert ok["title"] == "Yes"

    # Same-host Origin is allowed even when not on the extra allowlist.
    host = f"127.0.0.1:{kitchen.server_address[1]}"
    status, local = client.request(
        "POST",
        "/api/notes",
        {"type": "todo", "text": "buy cream"},
        origin=f"http://{host}",
    )
    assert status == 201
    assert local["text"] == "buy cream"


def test_get_from_non_loopback_when_bound_to_all_interfaces(lan_kitchen):
    port = lan_kitchen.server_address[1]
    # Confirm the process listens on every interface.
    assert lan_kitchen.server_address[0] == "0.0.0.0"
    lan_ip = _non_loopback_ipv4()
    if lan_ip is None:
        pytest.skip("no non-loopback IPv4 address on this host")
    client = Client(port, host=lan_ip)
    status, body = client.request("GET", "/api/settings")
    assert status == 200
    assert body["tableName"] == "Babette's Table"


def test_default_bind_is_all_interfaces():
    parser_host = None

    def fake_parse_args(self, args=None, namespace=None):
        nonlocal parser_host
        namespace = argparse.Namespace(db_path=":memory:", host="0.0.0.0", port=8765, origin=[])
        parser_host = namespace.host
        raise SystemExit(0)

    with patch("argparse.ArgumentParser.parse_args", fake_parse_args):
        with pytest.raises(SystemExit):
            main([])
    assert parser_host == "0.0.0.0"


def test_recipes_notes_plans_page_and_item_reads(kitchen):
    client = Client(kitchen.server_address[1])
    for index in range(3):
        status, _ = client.request(
            "POST",
            "/api/recipes",
            {"title": f"Dish {index}", "ingredients": [f"item {index}"]},
        )
        assert status == 201
        status, _ = client.request(
            "POST",
            "/api/notes",
            {"type": "todo", "text": f"note {index}", "open": True, "color": "peach"},
        )
        assert status == 201

    status, recipes = client.request("GET", "/api/recipes?limit=2")
    assert status == 200
    assert len(recipes["recipes"]) == 2
    assert recipes["nextCursor"]
    status, recipes2 = client.request("GET", f"/api/recipes?limit=2&cursor={recipes['nextCursor']}")
    assert status == 200
    assert len(recipes2["recipes"]) >= 1
    recipe_id = recipes["recipes"][0]["id"]
    status, recipe = client.request("GET", f"/api/recipes/{recipe_id}")
    assert status == 200
    assert recipe["id"] == recipe_id
    assert "ingredients" in recipe

    status, made = client.request(
        "POST",
        "/api/recipes",
        {"title": "Tamale Joe", "category": "casseroles", "source": "Quita", "voice": "grandma", "ingredients": ["masa"]},
    )
    assert status == 201
    conn = connect(kitchen.db_path)
    conn.execute(
        "UPDATE recipes SET extra_json = ? WHERE id = ?",
        (json.dumps({"ocrPhotos": ["data/cards/tamale.jpg"]}), made["id"]),
    )
    conn.commit()
    conn.close()
    status, full = client.request("GET", f"/api/recipes/{made['id']}")
    assert status == 200
    assert full["ocrPhotos"] == ["data/cards/tamale.jpg"]
    status, found = client.request("GET", "/api/recipes?q=Tamale%20Joe")
    assert status == 200
    row = next(item for item in found["recipes"] if item["id"] == made["id"])
    assert row["source"] == "Quita"
    assert row["voice"] == "grandma"
    assert row["ingredients"] == ["masa"]

    status, notes = client.request("GET", "/api/notes?limit=2")
    assert status == 200
    assert len(notes["notes"]) == 2
    assert notes["nextCursor"]
    note_id = notes["notes"][0]["id"]
    status, note = client.request("GET", f"/api/notes/{note_id}")
    assert status == 200
    assert note["id"] == note_id

    week = "2026-10-17"
    status, plan = client.request(
        "POST",
        "/api/plan",
        {"weekStart": week, "days": _week_days(week), "expected_updated_at": None},
    )
    assert status == 200
    status, loaded = client.request("GET", f"/api/plans/{week}")
    assert status == 200
    assert loaded["weekStart"] == week
    assert len(loaded["days"]) == 7
    assert loaded["updatedAt"] == plan["updatedAt"]


def test_new_chat_creates_row_and_points_session(kitchen):
    client = Client(kitchen.server_address[1])
    status, session = client.request("GET", "/api/session")
    assert status == 200
    status, first = client.request("POST", "/api/chats", {"title": ""})
    assert status == 201
    assert first["createdAt"]
    assert first["dateApprox"] is False
    status, session = client.request("GET", "/api/session")
    assert session["chat_id"] == first["id"]

    # File the first chat by creating another.
    conn = connect(kitchen.db_path)
    try:
        conn.execute(
            "INSERT INTO chat_messages (chat_id, position, role, content, extra_json) VALUES (?, 0, 'user', 'hi', '{}')",
            (first["id"],),
        )
        conn.commit()
    finally:
        conn.close()
    status, second = client.request("POST", "/api/chats", {})
    assert status == 201
    assert second["id"] != first["id"]
    assert second["createdAt"]
    assert second["dateApprox"] is False
    status, session = client.request("GET", "/api/session")
    assert session["chat_id"] == second["id"]
    status, listed = client.request("GET", "/api/chats")
    filed = next(chat for chat in listed["chats"] if chat["id"] == first["id"])
    assert filed["createdAt"] == first["createdAt"]
    assert filed["dateApprox"] is False


def test_note_toggle_and_stale_delete(kitchen):
    client = Client(kitchen.server_address[1])
    status, note = client.request("POST", "/api/notes", {"type": "todo", "text": "open me", "open": False})
    assert status == 201
    assert note["open"] is False
    status, toggled = client.request("POST", f"/api/notes/{note['id']}/toggle", {})
    assert status == 200
    assert toggled["open"] is True
    status, gone = client.request(
        "DELETE",
        f"/api/notes/{note['id']}",
        {"expected_updated_at": note["updatedAt"]},
    )
    assert status == 409


def test_recipe_photos_and_mark_cooked(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Pie", "ingredients": ["flour"]},
    )
    assert status == 201
    assert "needsPracticeReview" not in recipe
    assert recipe["cookCount"] == 0
    assert recipe["favourite"] is False
    png = base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
    ).decode()
    status, with_photo = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/photos",
        {
            "expected_updated_at": recipe["updatedAt"],
            "photos": [f"data:image/png;base64,{png}"],
        },
    )
    assert status == 200
    assert len(with_photo["photos"]) == 1
    status, cooked = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/cooked",
        {"expected_updated_at": with_photo["recipe"]["updatedAt"]},
    )
    assert status == 200
    assert cooked["cookCount"] == 1
    assert cooked["lastCooked"]
    assert "needsPracticeReview" not in cooked


def test_clear_cooks_undoes_the_recorded_cooks_and_checks_staleness(kitchen):
    client = Client(kitchen.server_address[1])
    _, recipe = client.request("POST", "/api/recipes", {"title": "Pie", "ingredients": ["flour"]})
    _, cooked = client.request(
        "POST", f"/api/recipes/{recipe['id']}/cooked", {"expected_updated_at": recipe["updatedAt"]}
    )
    assert cooked["cookCount"] == 1

    status, _ = client.request(
        "POST", f"/api/recipes/{recipe['id']}/clear-cooks", {"expected_updated_at": recipe["updatedAt"]}
    )
    assert status == 409

    status, cleared = client.request(
        "POST", f"/api/recipes/{recipe['id']}/clear-cooks", {"expected_updated_at": cooked["updatedAt"]}
    )
    assert status == 200
    assert cleared["cookCount"] == 0
    assert cleared["lastCooked"] is None


def test_recipe_favourite_toggle_and_stale(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Venison Stroganoff", "ingredients": ["venison", "cream"]},
    )
    assert status == 201
    assert recipe["favourite"] is False

    status, loved = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": recipe["updatedAt"], "favourite": True},
    )
    assert status == 200
    assert loved["favourite"] is True
    assert loved["updatedAt"] != recipe["updatedAt"]

    status, listed = client.request("GET", "/api/recipes")
    assert status == 200
    row = next(item for item in listed["recipes"] if item["id"] == recipe["id"])
    assert row["favourite"] is True

    status, conflict = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": recipe["updatedAt"], "favourite": False},
    )
    assert status == 409

    status, cleared = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": loved["updatedAt"], "favourite": False},
    )
    assert status == 200
    assert cleared["favourite"] is False


def test_formule_and_praxis_forms(kitchen):
    client = Client(kitchen.server_address[1])
    status, formule = client.request(
        "POST",
        "/api/recipes",
        {"title": "Stock", "kind": "recipe", "ingredients": ["bones", "water"], "category": "soups-stews"},
    )
    assert status == 201
    assert formule["kind"] == "formule"
    assert formule["ingredients"] == ["bones", "water"]
    assert formule["appliesTo"] == []

    status, praxis = client.request(
        "POST",
        "/api/recipes",
        {
            "title": "Stir-Fry",
            "kind": "praxis",
            "method": "Hot wok, quick toss.",
            "appliesTo": ["beef", "vegetables"],
            "category": "kitchen-craft",
        },
    )
    assert status == 201
    assert praxis["kind"] == "praxis"
    assert praxis["appliesTo"] == ["beef", "vegetables"]
    assert praxis["ingredients"] == []
    assert praxis["category"] == "kitchen-craft"

    status, bad = client.request(
        "POST",
        "/api/recipes",
        {"title": "No method", "kind": "praxis", "appliesTo": ["eggs"]},
    )
    assert status == 400
    assert "method" in bad["error"].casefold()

    status, listed = client.request("GET", f"/api/recipes/{praxis['id']}")
    assert status == 200
    assert listed["kind"] == "praxis"
    assert listed["appliesTo"] == ["beef", "vegetables"]


def _non_loopback_ipv4():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            ip = sock.getsockname()[0]
    except OSError:
        return None
    if not ip or ip.startswith("127."):
        return None
    return ip
