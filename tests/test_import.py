"""One small fixture per import guarantee, plus the live copy run twice."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from festin.importer import import_directory
from festin.schema import connect

LIVE = Path("/mnt/echo/festin-wt/live-copy")
WEEKDAYS = ("sat", "sun", "mon", "tue", "wed", "thu", "fri")


def dump(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def _days():
    return [{"day": day, "recipe": None, "title": "", "ingredients": []} for day in WEEKDAYS]


def write_copy(
    root: Path,
    *,
    journal=None,
    plan=None,
    recipes=None,
    memory=None,
    settings=None,
    template=False,
    chats=None,
    messages=None,
    active_chat_id=None,
):
    plans = root / "plans"
    plans.mkdir(parents=True)
    if template:
        (plans / "_template.json").write_text(
            '{"weekStart": "YYYY-MM-DD", "days": []}\n',
            encoding="utf-8",
        )
    body = {"weekStart": "2026-10-17", "days": _days(), "notes": ""}
    if plan:
        if "days" in plan:
            body["days"] = plan["days"]
        body.update({key: value for key, value in plan.items() if key != "days"})
    (plans / f"{body['weekStart']}.json").write_text(json.dumps(body), encoding="utf-8")
    state = {
        "journal": journal or [],
        "chats": chats if chats is not None else [],
        "messages": messages if messages is not None else [],
        "settings": {"family": "Holliday", "dinner_hour": "17:30"} if settings is None else settings,
    }
    if active_chat_id is not None:
        state["activeChatId"] = active_chat_id
    (root / "babette.json").write_text(json.dumps(state), encoding="utf-8")
    if recipes is not None:
        (root / "recipes.json").write_text(json.dumps(recipes), encoding="utf-8")
    if memory is not None:
        (root / "memory.json").write_text(json.dumps(memory), encoding="utf-8")
    return root


def test_nights_land_on_real_dates(tmp_path):
    root = write_copy(tmp_path / "live")
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    start = date.fromisoformat("2026-10-17")
    rows = conn.execute("SELECT date FROM nights ORDER BY date").fetchall()
    assert [row["date"] for row in rows] == [
        (start + timedelta(days=index)).isoformat() for index in range(7)
    ]
    assert conn.execute("SELECT date FROM nights WHERE date = '2026-10-17'").fetchone()["date"]
    conn.close()


def test_slip_quote_becomes_slip_title(tmp_path):
    quote = "Que la chaleur de la table console et rassemble."
    root = write_copy(tmp_path / "live", plan={"slipQuote": quote})
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    assert conn.execute("SELECT slip_title FROM weeks WHERE start_date = '2026-10-17'").fetchone()[0] == quote
    conn.close()


def test_note_priority_null_when_absent_and_kept_when_set(tmp_path):
    root = write_copy(
        tmp_path / "live",
        journal=[
            {"id": "bare", "type": "todo", "text": "no priority", "open": True, "color": "peach", "date": "2026-09-01"},
            {"id": "set", "type": "todo", "text": "has one", "open": True, "color": "peach", "priority": "low", "date": "2026-09-01"},
        ],
    )
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    assert conn.execute("SELECT priority FROM notes WHERE id = 'bare'").fetchone()[0] is None
    assert conn.execute("SELECT priority FROM notes WHERE id = 'set'").fetchone()[0] == "low"
    conn.close()


def test_note_open_and_closed_are_kept(tmp_path):
    root = write_copy(
        tmp_path / "live",
        journal=[
            {"id": "open-note", "type": "todo", "text": "still open", "open": True, "color": "peach", "date": "2026-09-01"},
            {"id": "shut-note", "type": "todo", "text": "done", "open": False, "color": "peach", "date": "2026-09-01"},
        ],
    )
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    assert conn.execute("SELECT open FROM notes WHERE id = 'open-note'").fetchone()[0] == 1
    assert conn.execute("SELECT open FROM notes WHERE id = 'shut-note'").fetchone()[0] == 0
    conn.close()


def test_imported_chat_date_from_earliest_plan_week_start(tmp_path):
    root = write_copy(
        tmp_path / "live",
        chats=[
            {
                "id": "with-plans",
                "title": "Dinner talk",
                "messages": [
                    {
                        "role": "user",
                        "content": "later week",
                        "plan": {"weekStart": "2026-10-17", "days": _days()},
                    },
                    {"role": "assistant", "content": "oui"},
                    {
                        "role": "user",
                        "content": "earlier week",
                        "plan": {"weekStart": "2026-09-12", "days": _days()},
                    },
                ],
            },
            {
                "id": "no-plans",
                "title": "Undated",
                "messages": [
                    {"role": "user", "content": "no plan attached"},
                    {"role": "assistant", "content": "still here"},
                ],
            },
        ],
    )
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    dated = conn.execute(
        "SELECT created_at, date_approx FROM chats WHERE id = 'with-plans'"
    ).fetchone()
    assert dated["created_at"] == "2026-09-12"
    assert dated["date_approx"] == 1
    bare = conn.execute(
        "SELECT created_at, date_approx FROM chats WHERE id = 'no-plans'"
    ).fetchone()
    assert bare["created_at"] is None
    assert bare["date_approx"] == 0
    conn.close()


def test_imported_chat_future_plan_week_clamps_to_import_week(tmp_path):
    """A chat that only plans next week is dated to this week's start, still approx."""
    root = write_copy(
        tmp_path / "live",
        settings={
            "family": "Holliday",
            "dinner_hour": "17:30",
            "weather": {
                "location": "83835",
                "label": "Hayden, Idaho, United States",
                "latitude": 47.76602,
                "longitude": -116.78658,
                "timezone": "America/Los_Angeles",
            },
        },
        chats=[
            {
                "id": "ahead",
                "title": "Planning ahead",
                "messages": [
                    {
                        "role": "user",
                        "content": "next Saturday's slip",
                        "plan": {"weekStart": "2026-10-24", "days": _days()},
                    },
                    {"role": "assistant", "content": "noted"},
                ],
            },
        ],
    )
    db = tmp_path / "store.sqlite"
    # Sunday 2026-10-18 in America/Los_Angeles; week starts Saturday → 2026-10-17.
    import_at = datetime(2026, 10, 18, 22, 0, tzinfo=timezone.utc)
    import_directory(root, db, now=import_at)
    conn = connect(db)
    row = conn.execute(
        "SELECT created_at, date_approx FROM chats WHERE id = 'ahead'"
    ).fetchone()
    assert row["created_at"] == "2026-10-17"
    assert row["date_approx"] == 1
    first = dump(db)
    import_directory(root, db, now=import_at)
    assert dump(db) == first
    conn.close()


def test_preference_kind_is_kept(tmp_path):
    root = write_copy(
        tmp_path / "live",
        journal=[
            {
                "id": "pref",
                "type": "preference",
                "text": "keep the archive",
                "open": False,
                "priority": "normal",
                "color": "lavender",
                "date": "2026-09-01",
            }
        ],
    )
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    row = conn.execute("SELECT kind, open, priority FROM notes WHERE id = 'pref'").fetchone()
    assert row["kind"] == "preference"
    assert row["open"] == 0
    assert row["priority"] == "normal"
    conn.close()


def test_note_colour_is_kept(tmp_path):
    root = write_copy(
        tmp_path / "live",
        journal=[
            {"id": "tinted", "type": "dinner", "text": "yellow card", "open": True, "color": "flamingo", "date": "2026-09-01"}
        ],
    )
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    assert conn.execute("SELECT color FROM notes WHERE id = 'tinted'").fetchone()[0] == "flamingo"
    conn.close()


def test_recipe_id_cbk_10000_round_trips(tmp_path):
    root = write_copy(
        tmp_path / "live",
        recipes={
            "meta": {"nextNumericId": 6},
            "recipes": [{"id": "CBK-10000", "title": "Past the cap", "ingredients": ["salt"]}],
        },
    )
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    row = conn.execute("SELECT id, title FROM recipes").fetchone()
    assert row["id"] == "CBK-10000"
    assert row["title"] == "Past the cap"
    assert conn.execute("SELECT next_numeric_id FROM catalog_meta").fetchone()[0] == 10001
    conn.close()


def test_table_name_appends_table(tmp_path):
    root = write_copy(tmp_path / "live", settings={"family": "Holliday", "dinner_hour": "17:30"})
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    assert conn.execute("SELECT table_name FROM settings").fetchone()[0] == "Holliday Table"
    conn.close()


def test_import_carries_weather_and_dinner_hour(tmp_path):
    settings = {
        "family": "Babette's",
        "dinner_hour": "18:45",
        "weather": {
            "location": "83835",
            "label": "Hayden, Idaho, United States",
            "latitude": 47.76602,
            "longitude": -116.78658,
            "timezone": "America/Los_Angeles",
        },
    }
    root = write_copy(tmp_path / "live", settings=settings)
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    row = conn.execute(
        """
        SELECT table_name, dinner_hour, weather_location, weather_label,
               weather_latitude, weather_longitude, weather_timezone
        FROM settings WHERE id = 1
        """
    ).fetchone()
    assert row["table_name"] == "Babette's Table"
    assert row["dinner_hour"] == "18:45"
    assert row["weather_location"] == "83835"
    assert row["weather_label"] == "Hayden, Idaho, United States"
    assert row["weather_latitude"] == 47.76602
    assert row["weather_longitude"] == -116.78658
    assert row["weather_timezone"] == "America/Los_Angeles"
    first = dump(db)
    conn.close()

    import_directory(root, db)
    assert dump(db) == first


def test_template_plan_is_skipped(tmp_path):
    root = write_copy(tmp_path / "live", template=True)
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    rows = conn.execute("SELECT start_date FROM weeks").fetchall()
    assert [row["start_date"] for row in rows] == ["2026-10-17"]
    conn.close()


def test_reimport_updates_the_edited_recipe_only(tmp_path):
    recipes = {
        "meta": {"nextNumericId": 3},
        "recipes": [
            {"id": "CBK-0001", "title": "Soup", "ingredients": ["water"], "updatedAt": "2026-01-01T00:00:00+00:00"},
            {"id": "CBK-0002", "title": "Bread", "ingredients": ["flour"], "updatedAt": "2026-01-02T00:00:00+00:00"},
        ],
    }
    root = write_copy(tmp_path / "live", recipes=recipes)
    db = tmp_path / "store.sqlite"
    import_directory(root, db)
    conn = connect(db)
    before = dict(conn.execute("SELECT * FROM recipes WHERE id = 'CBK-0002'").fetchone())
    conn.close()

    recipes["recipes"][0]["title"] = "Stew"
    (root / "recipes.json").write_text(json.dumps(recipes), encoding="utf-8")
    import_directory(root, db)
    conn = connect(db)
    assert conn.execute("SELECT title FROM recipes WHERE id = 'CBK-0001'").fetchone()[0] == "Stew"
    assert dict(conn.execute("SELECT * FROM recipes WHERE id = 'CBK-0002'").fetchone()) == before
    conn.close()


def test_import_twice_matches_the_live_copy(tmp_path):
    assert LIVE.is_dir(), "live snapshot is missing"
    before = _files(LIVE)
    db = tmp_path / "store.sqlite"
    import_directory(LIVE, db)
    first = dump(db)
    import_directory(LIVE, db)
    assert dump(db) == first
    assert _files(LIVE) == before

    conn = connect(db)
    _assert_live_plans(conn)
    _assert_live_notes(conn)
    _assert_live_chats(conn)
    dangling = conn.execute(
        """
        SELECT nights.recipe_id FROM nights
        WHERE nights.recipe_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM recipes WHERE recipes.id = nights.recipe_id)
        """
    ).fetchall()
    assert dangling == []
    conn.close()


def _files(root: Path) -> list[tuple[str, int]]:
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found.append((path.relative_to(root).as_posix(), path.stat().st_size))
    return found


def _assert_live_plans(conn):
    state = json.loads((LIVE / "babette.json").read_text(encoding="utf-8"))
    catalog = json.loads((LIVE / "recipes.json").read_text(encoding="utf-8"))
    plans = []
    for path in sorted((LIVE / "plans").glob("[0-9][0-9][0-9][0-9]-*.json")):
        plans.append(json.loads(path.read_text(encoding="utf-8")))
    assert conn.execute("SELECT count(*) FROM weeks").fetchone()[0] == len(plans)
    assert conn.execute("SELECT count(*) FROM nights").fetchone()[0] == len(plans) * 7
    assert conn.execute("SELECT count(*) FROM nights WHERE cooked != 0").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM recipes").fetchone()[0] == len(catalog["recipes"])

    sunday = conn.execute("SELECT recipe_id, title, cooked FROM nights WHERE date = '2026-10-18'").fetchone()
    assert sunday["recipe_id"] == "CBK-0933"
    assert sunday["title"] == "Venison Stroganoff"
    assert sunday["cooked"] == 0

    for plan in plans:
        start = date.fromisoformat(plan["weekStart"])
        assert start.weekday() == 5
        row = conn.execute(
            "SELECT slip_title, notes FROM weeks WHERE start_date = ?",
            (plan["weekStart"],),
        ).fetchone()
        quote = " ".join(plan["slipQuote"].split()) if plan.get("slipQuote") else ""
        assert row["slip_title"] == quote
        assert row["notes"] == (plan.get("notes") or "")
        for index, day in enumerate(plan["days"]):
            when = (start + timedelta(days=index)).isoformat()
            night = conn.execute(
                "SELECT recipe_id, title, week_start FROM nights WHERE date = ?",
                (when,),
            ).fetchone()
            assert night["week_start"] == plan["weekStart"]
            assert night["title"] == day["title"]
            assert night["recipe_id"] == (day["recipe"] or None)

    stored = conn.execute(
        """
        SELECT table_name, dinner_hour, week_start_day,
               weather_location, weather_label, weather_latitude,
               weather_longitude, weather_timezone,
               model_base_url, model_name
        FROM settings
        """
    ).fetchone()
    assert stored["table_name"] == state["settings"]["family"] + " Table"
    assert stored["dinner_hour"] == state["settings"]["dinner_hour"]
    assert stored["week_start_day"] == "sat"
    live_weather = state["settings"]["weather"]
    assert stored["weather_location"] == live_weather["location"]
    assert stored["weather_label"] == live_weather["label"]
    assert stored["weather_latitude"] == live_weather["latitude"]
    assert stored["weather_longitude"] == live_weather["longitude"]
    assert stored["weather_timezone"] == live_weather["timezone"]
    assert stored["model_base_url"] == state["settings"]["base_url"].rstrip("/")
    assert stored["model_name"] == state["settings"]["model"]


def _assert_live_notes(conn):
    journal = json.loads((LIVE / "babette.json").read_text(encoding="utf-8"))["journal"]
    memory = json.loads((LIVE / "memory.json").read_text(encoding="utf-8"))
    stored = {row["id"]: row for row in conn.execute("SELECT * FROM notes")}
    for note in journal:
        row = stored[note["id"]]
        assert row["kind"] == note["type"]
        assert row["text"] == note["text"]
        assert row["color"] == note["color"]
        assert row["open"] == (1 if note["open"] else 0)
        expected_priority = note["priority"] if "priority" in note else None
        assert row["priority"] == expected_priority
    preference = stored["755a1503-80d2-4802-aff9-b0f85f97703d"]
    assert preference["kind"] == "preference"
    for lane in ("household", "preferences", "restrictions"):
        row = stored[f"context-{lane}"]
        assert row["kind"] == lane
        assert row["text"] == memory["context"][lane]
        assert row["open"] == 0
    assert stored["REQ-0001"]["kind"] == "dinner"


def _assert_live_chats(conn):
    state = json.loads((LIVE / "babette.json").read_text(encoding="utf-8"))
    filed = conn.execute("SELECT count(*) FROM chats WHERE imported_active = 0").fetchone()[0]
    assert filed == len(state["chats"])
    active = conn.execute("SELECT id FROM chats WHERE imported_active = 1").fetchone()
    assert active["id"] == state["activeChatId"]
    messages = conn.execute("SELECT count(*) FROM chat_messages").fetchone()[0]
    expect = sum(len(chat["messages"]) for chat in state["chats"]) + len(state["messages"])
    assert messages == expect
    approx = conn.execute("SELECT count(*) FROM chats WHERE date_approx = 1").fetchone()[0]
    undated = conn.execute(
        "SELECT count(*) FROM chats WHERE created_at IS NULL AND date_approx = 0"
    ).fetchone()[0]
    assert approx + undated == conn.execute("SELECT count(*) FROM chats").fetchone()[0]
    assert approx >= 1
    assert undated >= 1
    sample = conn.execute(
        "SELECT id, created_at FROM chats WHERE date_approx = 1 ORDER BY created_at LIMIT 1"
    ).fetchone()
    assert sample["created_at"]
    date.fromisoformat(sample["created_at"])
