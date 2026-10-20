"""Kitchen Log over real HTTP: weeks, recipe/note events, chats, paging."""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from http.client import HTTPConnection
from unittest.mock import patch

import pytest

from festin.schema import connect
from festin.server import COOKIE
from tests.conftest import reset_db_file, start_kitchen, stop_kitchen


@pytest.fixture(scope="module")
def _log_server(migrated_template, tmp_path_factory):
    root = tmp_path_factory.mktemp("log")
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
def kitchen(_log_server):
    server, db, template = _log_server
    reset_db_file(db, template)
    yield server


class Client:
    def __init__(self, port: int):
        self.port = port
        self.cookie = None

    def request(self, method, path, body=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if self.cookie:
            headers["Cookie"] = f"{COOKIE}={self.cookie}"
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(raw))
        elif method in ("POST", "PUT", "DELETE"):
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = "0"
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        payload = json.loads(response.read().decode())
        issued = response.getheader("Set-Cookie")
        if issued:
            name, _, value = issued.split(";", 1)[0].partition("=")
            if name.strip() == COOKIE and value:
                self.cookie = value
        conn.close()
        return response.status, payload


def _week_days(start: str, *, titles=None, recipes=None, cooked=None):
    begin = date.fromisoformat(start)
    days = []
    for index in range(7):
        when = begin + timedelta(days=index)
        title = ""
        if titles and index < len(titles):
            title = titles[index]
        recipe = None
        if recipes and index < len(recipes):
            recipe = recipes[index]
        is_cooked = False
        if cooked and index < len(cooked):
            is_cooked = cooked[index]
        days.append(
            {
                "day": ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[when.weekday()],
                "title": title,
                "recipe": recipe,
                "ingredients": [],
                "cooked": is_cooked,
            }
        )
    return days


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
            "time": ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"],
            "weather_code": [0, 3, 61, 1, 2],
            "temperature_2m_min": [40.2, 42.0, 38.0, 41.0, 39.0],
            "temperature_2m_max": [60.8, 55.1, 50.0, 58.0, 57.0],
            "precipitation_probability_max": [10, 40, 80, 20, 15],
        }
    }


def _response(payload: dict):
    import io

    return io.BytesIO(json.dumps(payload).encode())


def test_saving_plan_updates_week_log_entry_with_weather(kitchen):
    client = Client(kitchen.server_address[1])
    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_geocode_payload())
        client.request("POST", "/api/settings", {"weatherLocation": "83835"})

    # Past week: the household's current week is omitted from the log.
    week = "2026-09-05"
    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_forecast_payload())
        status, plan = client.request(
            "POST",
            f"/api/plans/{week}",
            {
                "weekStart": week,
                "slipTitle": "LE FESTIN",
                "days": _week_days(
                    week,
                    titles=["Soup", "Bread", "", "", "", "", ""],
                    recipes=["CBK-0001", None, None, None, None, None, None],
                    cooked=[True, False, False, False, False, False, False],
                ),
                "expected_updated_at": None,
            },
        )
    assert status == 200
    assert plan["slipTitle"] == "LE FESTIN"

    status, body = client.request("GET", "/api/log")
    assert status == 200
    weeks = [entry for entry in body["entries"] if entry["kind"] == "week"]
    assert len(weeks) == 1
    entry = weeks[0]
    assert entry["weekStart"] == week
    assert entry["slipTitle"] == "LE FESTIN"
    assert entry["nights"][0]["title"] == "Soup"
    assert entry["nights"][0]["recipe"] == "CBK-0001"
    assert entry["nights"][0]["cooked"] is True
    assert entry["nights"][1]["title"] == "Bread"
    assert entry["weather"] is not None
    assert entry["weather"]["summary"]
    assert entry["tattva"] is None

    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_forecast_payload())
        status, again = client.request(
            "POST",
            f"/api/plans/{week}",
            {
                "weekStart": week,
                "slipTitle": "Autumn table",
                "days": _week_days(week, titles=["Stew", "", "", "", "", "", ""]),
                "expected_updated_at": plan["updatedAt"],
            },
        )
    assert status == 200
    status, body = client.request("GET", "/api/log")
    week_entry = next(entry for entry in body["entries"] if entry["kind"] == "week")
    assert week_entry["slipTitle"] == "Autumn table"
    assert week_entry["nights"][0]["title"] == "Stew"


def test_recipe_and_note_writes_add_log_entries(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Leek soup", "ingredients": ["leeks"], "category": "soups-stews"},
    )
    assert status == 201
    status, edited = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": recipe["updatedAt"], "changes": {"title": "Leek & barley soup"}},
    )
    assert status == 200
    status, note = client.request(
        "POST",
        "/api/notes",
        {"type": "kitchen", "text": "Buy cream before Sunday"},
    )
    assert status == 201

    status, body = client.request("GET", "/api/log")
    assert status == 200
    kinds = [entry["kind"] for entry in body["entries"]]
    assert "recipe_added" in kinds
    assert "recipe_edited" in kinds
    assert "note_created" in kinds

    added = next(entry for entry in body["entries"] if entry["kind"] == "recipe_added")
    assert added["id"] == recipe["id"]
    assert added["title"] == "Leek soup"

    changed = next(entry for entry in body["entries"] if entry["kind"] == "recipe_edited")
    assert changed["id"] == recipe["id"]
    assert changed["title"] == "Leek & barley soup"

    created = next(entry for entry in body["entries"] if entry["kind"] == "note_created")
    assert created["id"] == note["id"]
    assert "Buy cream" in created["title"]
    assert created["type"] == "kitchen"

    # Newest first among the three writes.
    assert kinds.index("note_created") < kinds.index("recipe_edited") < kinds.index("recipe_added")


def test_chat_appears_linked_with_date_approx(kitchen):
    client = Client(kitchen.server_address[1])
    status, chat = client.request("POST", "/api/chats", {"title": "Market list"})
    assert status == 201
    assert chat["dateApprox"] is False

    # Imported-style approximate chat folds into its week; dated chats stay alone.
    # A chat reaches the Log once it holds a message.
    conn = connect(kitchen.db_path)
    try:
        conn.execute(
            "INSERT INTO chat_messages (chat_id, position, role, content, extra_json) VALUES (?, 0, 'user', 'eggs', '{}')",
            (chat["id"],),
        )
        conn.execute(
            """
            INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
            VALUES ('2026-04-18', 'Spring', '', NULL, '2026-04-18T12:00:00.000000Z', NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO chats (id, title, ordinal, imported_active, updated_at, created_at, date_approx)
            VALUES ('approx-1', 'Old thread', 0, 0, '2026-04-18T00:00:00.000000Z', '2026-04-18', 1)
            """
        )
        conn.execute(
            "INSERT INTO chat_messages (chat_id, position, role, content, extra_json) VALUES ('approx-1', 0, 'user', 'hello', '{}')"
        )
        conn.commit()
    finally:
        conn.close()

    status, body = client.request("GET", "/api/log")
    assert status == 200
    chats = [entry for entry in body["entries"] if entry["kind"] == "chat"]
    by_id = {entry["id"]: entry for entry in chats}
    assert chat["id"] in by_id
    assert by_id[chat["id"]]["dateApprox"] is False
    assert by_id[chat["id"]]["createdAt"] == chat["createdAt"]
    assert "approx-1" not in by_id
    week = next(entry for entry in body["entries"] if entry["kind"] == "week" and entry["weekStart"] == "2026-04-18")
    assert len(week["conversations"]) == 1
    assert week["conversations"][0]["id"] == "approx-1"
    assert week["conversations"][0]["title"] == "Old thread"


def test_chat_with_many_messages_is_one_log_entry_at_creation(kitchen):
    client = Client(kitchen.server_address[1])
    created_at = "2026-05-03T15:22:00.000000Z"
    conn = connect(kitchen.db_path)
    try:
        conn.execute(
            """
            INSERT INTO chats (id, title, ordinal, imported_active, updated_at, created_at, date_approx)
            VALUES ('busy-1', 'Market run', 0, 0, '2026-05-10T09:00:00.000000Z', ?, 0)
            """,
            (created_at,),
        )
        for position, (role, text) in enumerate(
            [
                ("user", "What is for dinner?"),
                ("assistant", "Soup."),
                ("user", "And bread?"),
                ("assistant", "Yes."),
                ("user", "Thank you."),
                ("assistant", "Anytime."),
            ]
        ):
            conn.execute(
                """
                INSERT INTO chat_messages (chat_id, position, role, content, extra_json)
                VALUES ('busy-1', ?, ?, ?, '{}')
                """,
                (position, role, text),
            )
        conn.commit()
    finally:
        conn.close()

    status, body = client.request("GET", "/api/log")
    assert status == 200
    chats = [entry for entry in body["entries"] if entry["kind"] == "chat" and entry["id"] == "busy-1"]
    assert len(chats) == 1
    assert chats[0]["createdAt"] == created_at
    assert chats[0]["at"] == created_at
    assert chats[0]["title"] == "Market run"


def test_log_omits_household_current_week(kitchen):
    """The slip already shows this week; older weeks stay in the ledger."""
    client = Client(kitchen.server_address[1])
    with patch("festin.weather.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = _response(_geocode_payload())
        client.request("POST", "/api/settings", {"weatherLocation": "83835"})

    current_week = "2026-10-17"  # Sat; contains 2026-10-18 in America/Los_Angeles
    older_week = "2026-09-05"
    frozen = date(2026, 10, 18)
    conn = connect(kitchen.db_path)
    try:
        for week, slip in ((current_week, "This week"), (older_week, "Last month")):
            conn.execute(
                """
                INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
                VALUES (?, ?, '', NULL, ?, NULL)
                """,
                (week, slip, f"{week}T12:00:00.000000Z"),
            )
        conn.commit()
    finally:
        conn.close()

    with patch("festin.log.household_today", return_value=frozen):
        status, body = client.request("GET", "/api/log")
    assert status == 200
    weeks = [entry for entry in body["entries"] if entry["kind"] == "week"]
    starts = [entry["weekStart"] for entry in weeks]
    assert older_week in starts
    assert current_week not in starts
    older = next(entry for entry in weeks if entry["weekStart"] == older_week)
    assert older["slipTitle"] == "Last month"


def test_log_pages_back_to_first_imported_week_newest_first(kitchen):
    """Imported weeks (no events table rows, empty weather) page newest → oldest."""
    client = Client(kitchen.server_address[1])
    starts = ["2026-04-18", "2026-05-16", "2026-06-13", "2026-07-11", "2026-08-08", "2026-09-05"]
    conn = connect(kitchen.db_path)
    try:
        for index, start in enumerate(starts):
            conn.execute(
                """
                INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
                VALUES (?, ?, '', NULL, ?, NULL)
                """,
                (start, f"Week {index}", f"{start}T12:00:00.000000Z"),
            )
            begin = date.fromisoformat(start)
            for offset in range(7):
                when = (begin + timedelta(days=offset)).isoformat()
                conn.execute(
                    """
                    INSERT INTO nights (date, week_start, recipe_id, title, cooked, updated_at)
                    VALUES (?, ?, NULL, ?, 0, ?)
                    """,
                    (when, start, f"Dish {offset}" if offset < 3 else "", f"{start}T12:00:00.000000Z"),
                )
        conn.commit()
    finally:
        conn.close()

    first_week = starts[0]
    last_week = starts[-1]
    seen_weeks = []
    before = None
    previous_last_at = None
    while True:
        path = "/api/log?limit=2"
        if before:
            path += f"&before={before}"
        status, body = client.request("GET", path)
        assert status == 200
        page = body["entries"]
        if not page:
            break
        ats = [entry["at"] for entry in page]
        assert ats == sorted(ats, reverse=True)
        if previous_last_at is not None:
            assert ats[0] <= previous_last_at
        previous_last_at = ats[-1]
        for entry in page:
            if entry["kind"] == "week":
                seen_weeks.append(entry["weekStart"])
                assert entry["weather"] is None
                assert entry["tattva"] is None
        before = body.get("nextCursor")
        if not before:
            break

    assert seen_weeks[0] == last_week
    assert seen_weeks[-1] == first_week
    assert seen_weeks == list(reversed(starts))


def test_derived_import_recipe_and_note_without_duplicate_api_events(kitchen):
    client = Client(kitchen.server_address[1])
    conn = connect(kitchen.db_path)
    try:
        conn.execute(
            """
            INSERT INTO recipes (
                id, title, kind, category, voice, source, provenance, status, stub,
                cooks_before_log, search_description, method, notes, context, ocr_text,
                ingredients_json, tattva_json, photos_json, created_at, updated_at, extra_json
            ) VALUES (
                'CBK-0099', 'Seeded rye', 'formule', 'breads', '', '', 'documented', 'ok', 0, 0,
                '', '', '', '', '', '[]', '[]', '[]',
                '2026-04-25T10:00:00.000000Z', '2026-05-01T12:00:00.000000Z', '{}'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO notes (
                id, kind, text, color, priority, open, written_on, updated_on, band, updated_at
            ) VALUES (
                'note-old', 'kitchen', 'Levain feeding', 'none', NULL, 0, '2026-06-20', NULL, NULL,
                '2026-06-20T00:00:00.000000Z'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    status, body = client.request("GET", "/api/log")
    assert status == 200
    added = [entry for entry in body["entries"] if entry["kind"] == "recipe_added" and entry["id"] == "CBK-0099"]
    edited = [entry for entry in body["entries"] if entry["kind"] == "recipe_edited" and entry["id"] == "CBK-0099"]
    notes = [entry for entry in body["entries"] if entry["kind"] == "note_created" and entry["id"] == "note-old"]
    assert len(added) == 1
    assert len(edited) == 1
    assert len(notes) == 1

    # API create still records exactly one add (no derived duplicate).
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Fresh loaf", "ingredients": ["flour"]},
    )
    assert status == 201
    status, body = client.request("GET", "/api/log")
    adds = [entry for entry in body["entries"] if entry["kind"] == "recipe_added" and entry["id"] == recipe["id"]]
    assert len(adds) == 1


def test_first_cook_favourite_archive_and_photo_log_once(kitchen, tmp_path):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {
            "title": "Barley stew",
            "ingredients": ["barley"],
            "category": "soups-stews",
        },
    )
    assert status == 201
    assert "needsPracticeReview" not in recipe
    assert recipe["cookCount"] == 0

    status, cooked = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/cooked",
        {"expected_updated_at": recipe["updatedAt"]},
    )
    assert status == 200
    assert cooked["cookCount"] == 1

    # Notes tweak after the cook: a plain edit, not another cook line.
    status, again = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {
            "expected_updated_at": cooked["updatedAt"],
            "changes": {"notes": "still good"},
        },
    )
    assert status == 200

    status, loved = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": again["updatedAt"], "favourite": True},
    )
    assert status == 200
    assert loved["favourite"] is True

    status, still = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {"expected_updated_at": loved["updatedAt"], "favourite": True},
    )
    assert status == 200

    status, note = client.request(
        "POST",
        "/api/notes",
        {"type": "kitchen", "text": "Soak the barley", "open": True},
    )
    assert status == 201
    status, archived = client.request(
        "POST",
        f"/api/notes/{note['id']}/toggle",
        {"expected_updated_at": note["updatedAt"]},
    )
    assert status == 200
    assert archived["open"] is False
    status, pinned = client.request(
        "POST",
        f"/api/notes/{note['id']}/toggle",
        {"expected_updated_at": archived["updatedAt"]},
    )
    assert status == 200
    assert pinned["open"] is True

    tiny_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    status, photos = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/photos",
        {"expected_updated_at": still["updatedAt"], "photos": [tiny_png]},
    )
    assert status == 200
    status, photos_again = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}/photos",
        {
            "expected_updated_at": photos["recipe"]["updatedAt"],
            "photos": [photos["photos"][0]],
        },
    )
    assert status == 200

    status, body = client.request("GET", "/api/log")
    assert status == 200
    by_kind = {}
    for entry in body["entries"]:
        if entry.get("id") in (recipe["id"], note["id"]):
            by_kind.setdefault(entry["kind"], []).append(entry)

    assert len(by_kind.get("recipe_cooked", [])) == 1
    assert by_kind["recipe_cooked"][0]["title"] == "Barley stew"
    assert "recipe_edited" in by_kind  # the notes tweak after first cook
    assert len(by_kind.get("recipe_favourited", [])) == 1
    assert len(by_kind.get("note_archived", [])) == 1
    assert by_kind["note_archived"][0]["title"].startswith("Soak the barley")
    assert len(by_kind.get("photo_added", [])) == 1
    assert by_kind["photo_added"][0]["detail"] == "1"


def test_needs_practice_review_is_rejected(kitchen):
    client = Client(kitchen.server_address[1])
    status, recipe = client.request(
        "POST",
        "/api/recipes",
        {"title": "Rye", "ingredients": ["rye"]},
    )
    assert status == 201
    assert "needsPracticeReview" not in recipe
    status, body = client.request(
        "POST",
        f"/api/recipes/{recipe['id']}",
        {
            "expected_updated_at": recipe["updatedAt"],
            "changes": {"needsPracticeReview": False},
        },
    )
    assert status == 400
    assert "needsPracticeReview" in str(body)


def test_approx_chats_fold_into_week_summary(kitchen):
    client = Client(kitchen.server_address[1])
    week = "2026-05-16"
    conn = connect(kitchen.db_path)
    try:
        conn.execute(
            """
            INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
            VALUES (?, 'May table', '', NULL, ?, NULL)
            """,
            (week, f"{week}T12:00:00.000000Z"),
        )
        for index in range(3):
            chat_id = f"fold-{index}"
            conn.execute(
                """
                INSERT INTO chats (id, title, ordinal, imported_active, updated_at, created_at, date_approx)
                VALUES (?, ?, ?, 0, ?, ?, 1)
                """,
                (
                    chat_id,
                    f"Thread {index}",
                    index,
                    f"{week}T00:00:00.000000Z",
                    week,
                ),
            )
            conn.execute(
                "INSERT INTO chat_messages (chat_id, position, role, content, extra_json) VALUES (?, 0, 'user', ?, '{}')",
                (chat_id, f"hello {index}"),
            )
        # Dated chat stays on the timeline.
        conn.execute(
            """
            INSERT INTO chats (id, title, ordinal, imported_active, updated_at, created_at, date_approx)
            VALUES ('dated-1', 'Fresh', 9, 0, '2026-05-20T15:00:00.000000Z', '2026-05-20T15:00:00.000000Z', 0)
            """
        )
        conn.execute(
            "INSERT INTO chat_messages (chat_id, position, role, content, extra_json) VALUES ('dated-1', 0, 'user', 'hi', '{}')"
        )
        conn.commit()
    finally:
        conn.close()

    status, body = client.request("GET", "/api/log")
    assert status == 200
    week_entry = next(entry for entry in body["entries"] if entry["kind"] == "week" and entry["weekStart"] == week)
    assert len(week_entry["conversations"]) == 3
    assert {c["id"] for c in week_entry["conversations"]} == {"fold-0", "fold-1", "fold-2"}
    chat_ids = {entry["id"] for entry in body["entries"] if entry["kind"] == "chat"}
    assert "dated-1" in chat_ids
    assert not ({"fold-0", "fold-1", "fold-2"} & chat_ids)


def test_week_in_progress_has_no_box_and_its_events_stay_loose(kitchen):
    client = Client(kitchen.server_address[1])
    current_week = "2026-10-17"
    conn = connect(kitchen.db_path)
    try:
        conn.execute(
            """
            INSERT INTO weeks (start_date, slip_title, notes, plates_json, updated_at, weather_json)
            VALUES (?, 'This week', '', NULL, ?, NULL)
            """,
            (current_week, f"{current_week}T12:00:00.000000Z"),
        )
        conn.execute(
            "INSERT INTO nights (week_start, date, title) VALUES (?, '2026-10-18', 'Stroganoff')",
            (current_week,),
        )
        conn.execute(
            """
            INSERT INTO chats (id, title, ordinal, imported_active, updated_at, created_at, date_approx)
            VALUES ('old-1', 'Imported', 0, 0, NULL, ?, 1)
            """,
            (current_week,),
        )
        conn.execute(
            "INSERT INTO chat_messages (chat_id, position, role, content, extra_json) VALUES ('old-1', 0, 'user', 'hi', '{}')"
        )
        conn.commit()
    finally:
        conn.close()

    with patch("festin.log.household_today", return_value=date(2026, 10, 18)):
        status, body = client.request("GET", "/api/log")
    assert status == 200
    # The week in progress gets no box; its events, imported chats included, stay loose.
    assert not [e for e in body["entries"] if e["kind"] == "week"]
    assert [e["id"] for e in body["entries"] if e["kind"] == "chat"] == ["old-1"]
