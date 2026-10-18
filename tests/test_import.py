"""The import run twice yields one database, and the live facts survive."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from festin.importer import import_directory
from festin.schema import apply, connect

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("/mnt/echo/festin-wt/live-copy")


def dump(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return "\n".join(conn.iterdump())
    finally:
        conn.close()


def test_schema_accepts_a_recipe_past_cbk_9999(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    apply(conn)
    apply(conn)
    conn.execute("INSERT INTO recipes (id, title) VALUES ('CBK-10000', 'Past the cap')")
    conn.execute("INSERT INTO weeks (start_date) VALUES ('2026-10-17')")
    conn.execute(
        """
        INSERT INTO nights (date, week_start, recipe_id, title, cooked)
        VALUES ('2026-10-18', '2026-10-17', 'CBK-10000', 'Past the cap', 0)
        """
    )
    conn.commit()
    row = conn.execute("SELECT recipe_id, cooked FROM nights WHERE date = '2026-10-18'").fetchone()
    assert row["recipe_id"] == "CBK-10000"
    assert row["cooked"] == 0
    assert conn.execute("SELECT count(*) FROM note_colors").fetchone()[0] == 15
    assert conn.execute("SELECT table_name FROM settings").fetchone()[0] == "Babette's Table"


def test_import_twice_matches_and_keeps_live_facts(tmp_path):
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
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "slips" not in tables
    assert "status_pane" not in tables
    conn.close()


def test_recipe_ids_are_not_capped_and_memory_notes_are_stable(tmp_path):
    data = tmp_path / "live"
    plans = data / "plans"
    plans.mkdir(parents=True)
    (plans / "_template.json").write_text('{"weekStart": "YYYY-MM-DD", "days": []}\n', encoding="utf-8")
    (plans / "2026-10-17.json").write_text(
        json.dumps(
            {
                "weekStart": "2026-10-17",
                "slipQuote": "Que la chaleur de la table console et rassemble.",
                "notes": "open nights",
                "days": [
                    {"day": "sat", "recipe": None, "title": "", "ingredients": []},
                    {"day": "sun", "recipe": "CBK-10000", "title": "Past the cap", "ingredients": ["salt"]},
                    {"day": "mon", "recipe": "CBK-1366", "title": "Marry Me Chicken Pasta", "ingredients": []},
                    {"day": "tue", "recipe": None, "title": "", "ingredients": []},
                    {"day": "wed", "recipe": None, "title": "", "ingredients": []},
                    {"day": "thu", "recipe": None, "title": "", "ingredients": []},
                    {"day": "fri", "recipe": None, "title": "", "ingredients": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "recipes.json").write_text(
        json.dumps(
            {
                "meta": {"nextNumericId": 6},
                "recipes": [
                    {"id": "CBK-1366", "title": "Marry Me Chicken Pasta", "ingredients": ["chicken"]},
                    {
                        "id": "CBK-10000",
                        "title": "Past the cap",
                        "ingredients": ["salt"],
                        "kind": "recipe",
                        "unmappedField": "kept",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (data / "memory.json").write_text(
        json.dumps(
            {
                "standing": ["thyme on the table"],
                "standingDates": {"thyme on the table": "2026-01-02"},
                "standingMeta": {"thyme on the table": {"priority": "high", "updated": "2026-02-03"}},
                "context": {"household": "two cooks", "preferences": "", "restrictions": ""},
            }
        ),
        encoding="utf-8",
    )
    (data / "babette.json").write_text(
        json.dumps(
            {
                "journal": [
                    {
                        "id": "755a1503-80d2-4802-aff9-b0f85f97703d",
                        "type": "preference",
                        "text": "keep the archive",
                        "open": False,
                        "priority": "normal",
                        "color": "lavender",
                        "date": "2026-09-01",
                    }
                ],
                "chats": [
                    {"id": "chat-1", "title": "Thyme", "messages": [{"role": "user", "content": "thyme?"}]}
                ],
                "messages": [{"role": "user", "content": "still talking"}],
                "activeChatId": "chat-active",
                "settings": {"family": "Babette's Table", "dinner_hour": "17:30"},
            }
        ),
        encoding="utf-8",
    )
    db = tmp_path / "store.sqlite"
    import_directory(data, db)
    first = dump(db)
    import_directory(data, db)
    assert dump(db) == first

    conn = connect(db)
    conn.execute(
        "INSERT INTO sessions (id, created_at, updated_at, chat_id, draft) VALUES ('dev', 't0', 't1', 'chat-1', 'half')"
    )
    conn.execute("INSERT INTO plugin_settings (plugin_id, settings_json) VALUES ('printer', '{}')")
    conn.execute("UPDATE settings SET forecast_json = '{\"keep\":true}' WHERE id = 1")
    conn.commit()
    conn.close()
    import_directory(data, db)
    conn = connect(db)
    session = conn.execute("SELECT chat_id, draft FROM sessions WHERE id = 'dev'").fetchone()
    assert session["chat_id"] == "chat-1"
    assert session["draft"] == "half"
    assert conn.execute("SELECT count(*) FROM plugin_settings").fetchone()[0] == 1
    assert conn.execute("SELECT forecast_json FROM settings").fetchone()[0] == '{"keep":true}'
    conn.close()

    conn = connect(db)
    ids = {row["id"] for row in conn.execute("SELECT id FROM recipes")}
    assert ids == {"CBK-10000", "CBK-1366"}
    assert conn.execute("SELECT next_numeric_id FROM catalog_meta").fetchone()[0] == 10001
    extra = conn.execute("SELECT extra_json FROM recipes WHERE id = 'CBK-10000'").fetchone()[0]
    assert json.loads(extra) == {"unmappedField": "kept"}
    night = conn.execute("SELECT recipe_id, title, cooked FROM nights WHERE date = '2026-10-18'").fetchone()
    assert night["recipe_id"] == "CBK-10000"
    assert night["cooked"] == 0
    assert conn.execute("SELECT slip_title FROM weeks").fetchone()[0].startswith("Que la chaleur")
    preference = conn.execute(
        "SELECT kind, open, priority FROM notes WHERE id = '755a1503-80d2-4802-aff9-b0f85f97703d'"
    ).fetchone()
    assert preference["kind"] == "preference"
    assert preference["open"] == 0
    assert preference["priority"] == "normal"
    standing = conn.execute(
        "SELECT id, kind, priority, open FROM notes WHERE kind = 'preference' AND id LIKE 'standing-%'"
    ).fetchone()
    assert standing["priority"] == "high"
    assert standing["open"] == 0
    again = conn.execute("SELECT id FROM notes WHERE text = 'thyme on the table'").fetchone()[0]
    assert again == standing["id"]
    assert conn.execute("SELECT text FROM notes WHERE id = 'context-household'").fetchone()[0] == "two cooks"
    conn.close()

    completed = subprocess.run(
        [sys.executable, "-m", "festin.importer", str(data), str(tmp_path / "cli.sqlite")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "recipes\t2" in completed.stdout
    assert "nights\t7" in completed.stdout


def _files(root: Path) -> list[tuple[str, int]]:
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found.append((path.relative_to(root).as_posix(), path.stat().st_size))
    return found


def _assert_live_plans(conn):
    state = json.loads((LIVE / "babette.json").read_text(encoding="utf-8"))
    plans = []
    for path in sorted((LIVE / "plans").glob("[0-9][0-9][0-9][0-9]-*.json")):
        plans.append(json.loads(path.read_text(encoding="utf-8")))
    assert conn.execute("SELECT count(*) FROM weeks").fetchone()[0] == len(plans)
    assert conn.execute("SELECT count(*) FROM nights").fetchone()[0] == len(plans) * 7
    assert conn.execute("SELECT count(*) FROM nights WHERE cooked != 0").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM recipes").fetchone()[0] == 0

    sunday = conn.execute("SELECT recipe_id, title, cooked FROM nights WHERE date = '2026-10-18'").fetchone()
    assert sunday["recipe_id"] == "CBK-0933"
    assert sunday["title"] == "Venison Stroganoff"
    assert sunday["cooked"] == 0
    tuesday = conn.execute("SELECT recipe_id, title FROM nights WHERE date = '2026-10-13'").fetchone()
    assert tuesday["recipe_id"] == "CBK-1388"

    for plan in plans:
        start = date.fromisoformat(plan["weekStart"])
        assert start.weekday() == 5
        row = conn.execute(
            "SELECT slip_title, notes, plates_json FROM weeks WHERE start_date = ?",
            (plan["weekStart"],),
        ).fetchone()
        quote = " ".join(plan["slipQuote"].split()) if plan.get("slipQuote") else ""
        assert row["slip_title"] == quote
        assert row["notes"] == (plan.get("notes") or "")
        if isinstance(plan.get("slipPlates"), dict):
            assert json.loads(row["plates_json"]) == plan["slipPlates"]
        else:
            assert row["plates_json"] is None
        for index, day in enumerate(plan["days"]):
            when = (start + timedelta(days=index)).isoformat()
            night = conn.execute(
                "SELECT recipe_id, title, week_start FROM nights WHERE date = ?",
                (when,),
            ).fetchone()
            assert night["week_start"] == plan["weekStart"]
            assert night["title"] == day["title"]
            assert night["recipe_id"] == (day["recipe"] or None)
            stored = [
                item["text"]
                for item in conn.execute(
                    "SELECT text FROM night_ingredients WHERE date = ? ORDER BY position",
                    (when,),
                )
            ]
            assert stored == day["ingredients"]

    settings = state["settings"]
    stored = conn.execute(
        "SELECT table_name, dinner_hour, weather_location, timezone, week_start_day FROM settings"
    ).fetchone()
    assert stored["table_name"] == settings["family"]
    assert stored["dinner_hour"] == settings["dinner_hour"]
    assert stored["weather_location"] == settings["weather"]["location"]
    assert stored["timezone"] == settings["weather"]["timezone"]
    assert stored["week_start_day"] == "sat"


def _assert_live_notes(conn):
    journal = json.loads((LIVE / "babette.json").read_text(encoding="utf-8"))["journal"]
    stored = {row["id"]: row for row in conn.execute("SELECT * FROM notes")}
    assert set(stored) == {note["id"] for note in journal}
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
    assert preference["open"] == 0
    assert preference["priority"] == "normal"
    assert stored["REQ-0001"]["kind"] == "dinner"


def _assert_live_chats(conn):
    state = json.loads((LIVE / "babette.json").read_text(encoding="utf-8"))
    filed = conn.execute("SELECT count(*) FROM chats WHERE imported_active = 0").fetchone()[0]
    assert filed == len(state["chats"])
    active = conn.execute(
        "SELECT id, title FROM chats WHERE imported_active = 1"
    ).fetchone()
    assert active["id"] == state["activeChatId"]
    assert active["title"]
    messages = conn.execute("SELECT count(*) FROM chat_messages").fetchone()[0]
    expect = sum(len(chat["messages"]) for chat in state["chats"]) + len(state["messages"])
    assert messages == expect
